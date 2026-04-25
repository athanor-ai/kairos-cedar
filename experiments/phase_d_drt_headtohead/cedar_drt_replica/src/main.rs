// cedar_drt_replica/src/main.rs
//
// A standalone byte-level fuzzer that mirrors the reach-rate behaviour of
// cedar-drt's `simple-parser` and (a degraded form of) `abac-type-directed`
// fuzz targets, runnable inside the kairos-cedar image without
// cargo-fuzz / Lean FFI / the full cedar-spec build.
//
// Modes:
//   - `bytes`         : sample N random byte strings, attempt to parse as
//                       Cedar policyset, count parser-reach.  Mirrors the
//                       `simple-parser` fuzz target (input: String).
//   - `corpus-mutate` : libfuzzer-style: pick a random seed from a small
//                       corpus of valid Cedar policies, apply 1-3 small
//                       mutations (delete / duplicate / replace / insert
//                       a byte), then parse + eval.  Mirrors cedar-drt's
//                       `simple-parser` target with corpus seeding —
//                       which is what produces the paper's ~0.05
//                       byte-level reach rate when libfuzzer's coverage
//                       guidance is in play.
//   - `arbitrary`     : reserved.  cedar-drt's `arbitrary`-crate driven
//                       structured generation (`FuzzTargetInput`)
//                       requires `cedar-policy-generators` 4.0.0 which
//                       does not compile against cedar HEAD 4.10
//                       (69 errors with cap-lints), so we don't ship it
//                       here.  `bytes` and `corpus-mutate` are the two
//                       byte-level baselines we run instead.
//
// Output: one JSONL line per attempt + a summary line at the end.
//   Per-attempt: {"attempt", "bytes", "parsed", "evaluated", "decision",
//                 "elapsed_ms"}.  Pass --only-emit-parsed to suppress
//   the (large) non-parsed lines on long runs.
//   Summary: {"summary": {n_attempts, parsed, evaluated, allow, deny,
//                          parse_reach_rate, evaluator_reach_rate,
//                          total_bytes_consumed, elapsed_secs,
//                          attempts_per_sec, evaluator_reach_per_sec,
//                          cost_per_evaluator_reach_ms}}.
//
// Termination: either --n attempts or --time-budget-secs, whichever
// comes first.  At 13-min budget we expect ~10^7 to 10^8 attempts on
// modern hardware.

use std::env;
use std::str::FromStr;
use std::time::{Duration, Instant};

use cedar_policy::{
    Authorizer, Context, Entities, EntityUid, PolicySet, Request,
};
use cedar_policy_core::parser::parse_policyset;
use rand::{RngCore, SeedableRng};
use rand_chacha::ChaCha8Rng;

/// Tiny seed corpus of valid Cedar policies (matches the schema in
/// experiments/phase_c_diff/run_diff.py: User/Document/Photo + view/edit/admin).
/// libfuzzer-style mode mutates bytes around these templates to amplify
/// the reach rate the way cedar-drt's `simple-parser` corpus does.
const SEED_CORPUS: &[&str] = &[
    r#"permit(principal, action, resource);"#,
    r#"permit(principal == User::"alice", action == Action::"view", resource);"#,
    r#"forbid(principal, action == Action::"admin", resource);"#,
    r#"permit(principal, action, resource) when { principal == User::"alice" };"#,
    r#"permit(principal, action, resource) when { resource == Document::"doc1" };"#,
    r#"permit(principal == User::"bob", action in [Action::"view", Action::"edit"], resource);"#,
];

#[derive(Debug, Clone)]
struct Args {
    mode: String, // "bytes" | "corpus-mutate" | "arbitrary"
    n: usize,
    seed: u64,
    time_budget_secs: u64,
    max_byte_len: usize,
    min_byte_len: usize,
    progress_every: usize,
    /// Print per-attempt JSONL only when parsed=true.  Saves disk on long runs.
    only_emit_parsed: bool,
}

fn parse_args() -> Args {
    let mut a = Args {
        mode: "bytes".to_string(),
        n: 100_000,
        seed: 0xC0DE_FACE,
        time_budget_secs: 600,
        max_byte_len: 200,
        min_byte_len: 1,
        progress_every: 1000,
        only_emit_parsed: false,
    };
    let argv: Vec<String> = env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        let s = argv[i].as_str();
        match s {
            "--mode" => {
                i += 1;
                a.mode = argv[i].clone();
            }
            "--n" => {
                i += 1;
                a.n = argv[i].parse().expect("--n integer");
            }
            "--seed" => {
                i += 1;
                a.seed = argv[i].parse().expect("--seed integer");
            }
            "--time-budget-secs" => {
                i += 1;
                a.time_budget_secs =
                    argv[i].parse().expect("--time-budget-secs integer");
            }
            "--max-byte-len" => {
                i += 1;
                a.max_byte_len = argv[i].parse().expect("--max-byte-len integer");
            }
            "--min-byte-len" => {
                i += 1;
                a.min_byte_len = argv[i].parse().expect("--min-byte-len integer");
            }
            "--progress-every" => {
                i += 1;
                a.progress_every =
                    argv[i].parse().expect("--progress-every integer");
            }
            "--only-emit-parsed" => {
                a.only_emit_parsed = true;
            }
            _ => {
                eprintln!("unknown arg: {}", s);
                std::process::exit(2);
            }
        }
        i += 1;
    }
    a
}

fn build_fixed_setup() -> (Entities, Request) {
    // Fixed entities matching experiments/phase_c_diff/run_diff.py:
    // Users alice/bob/carol; Documents doc1/doc2; Photos photo1.
    let entities_json = r#"[
        {"uid": {"type": "User", "id": "alice"}, "attrs": {}, "parents": []},
        {"uid": {"type": "User", "id": "bob"}, "attrs": {}, "parents": []},
        {"uid": {"type": "User", "id": "carol"}, "attrs": {}, "parents": []},
        {"uid": {"type": "Document", "id": "doc1"}, "attrs": {}, "parents": []},
        {"uid": {"type": "Document", "id": "doc2"}, "attrs": {}, "parents": []},
        {"uid": {"type": "Photo", "id": "photo1"}, "attrs": {}, "parents": []}
    ]"#;
    let entities = Entities::from_json_str(entities_json, None).expect("entities parse");

    let p = EntityUid::from_str(r#"User::"alice""#).unwrap();
    let a = EntityUid::from_str(r#"Action::"view""#).unwrap();
    let r = EntityUid::from_str(r#"Document::"doc1""#).unwrap();
    let req = Request::new(p, a, r, Context::empty(), None).expect("request build");

    (entities, req)
}

/// Convert an arbitrary byte buffer to a (mostly invalid) Cedar policy text.
/// Mirrors how `simple-parser`'s fuzz_target consumes its `String` input.
fn bytes_to_policy_text(bytes: &[u8]) -> String {
    match std::str::from_utf8(bytes) {
        Ok(s) => s.to_string(),
        Err(_) => String::from_utf8_lossy(bytes).into_owned(),
    }
}

/// Parse + (if non-empty) evaluate a candidate policy text against fixed
/// entities and a fixed request.  Returns (parsed, evaluated, decision).
///
/// We reject empty PolicySets (from whitespace-only inputs) because they
/// "evaluate" trivially to Deny without exercising the evaluator —
/// counting them would inflate the reach rate.
fn try_parse_and_eval(
    text: &str,
    entities: &Entities,
    req: &Request,
    authorizer: &Authorizer,
) -> (bool, bool, String) {
    // Stage 1: cedar-policy-core parser (matches simple-parser semantics).
    if parse_policyset(text).is_err() {
        return (false, false, "ParseError".to_string());
    }

    // Stage 2: cedar-policy public API to build a PolicySet.
    let pset = match PolicySet::from_str(text) {
        Ok(p) => p,
        Err(_) => return (true, false, "PolicySetBuildError".to_string()),
    };

    // Reject empty policysets (vacuously Deny — does not exercise the evaluator).
    if pset.policies().count() == 0 {
        return (true, false, "EmptyPolicySet".to_string());
    }

    // Stage 3: evaluate.
    let resp = authorizer.is_authorized(req, &pset, entities);
    let dec = format!("{:?}", resp.decision());
    (true, true, dec)
}

fn main() {
    let args = parse_args();
    eprintln!(
        "[cedar_drt_replica] mode={} n={} seed={} time_budget_secs={} byte_len=[{},{}]",
        args.mode, args.n, args.seed, args.time_budget_secs,
        args.min_byte_len, args.max_byte_len
    );

    let (entities, req) = build_fixed_setup();
    let authorizer = Authorizer::new();

    let mut rng = ChaCha8Rng::seed_from_u64(args.seed);
    let mut buf = vec![0u8; args.max_byte_len];

    let t0 = Instant::now();
    let budget = Duration::from_secs(args.time_budget_secs);

    let mut attempts: u64 = 0;
    let mut parsed_count: u64 = 0;
    let mut evaluated_count: u64 = 0;
    let mut allow_count: u64 = 0;
    let mut deny_count: u64 = 0;
    let mut total_bytes: u64 = 0;

    while attempts < args.n as u64 {
        if t0.elapsed() >= budget {
            eprintln!(
                "[cedar_drt_replica] time budget exhausted at attempt {}",
                attempts
            );
            break;
        }

        // Pick a random length within [min, max].
        let max_len = args.max_byte_len.max(args.min_byte_len);
        let min_len = args.min_byte_len;
        let len_range = max_len - min_len + 1;
        let len = min_len + (rng.next_u32() as usize % len_range);
        let len = len.min(args.max_byte_len);

        rng.fill_bytes(&mut buf[..len]);

        let text = match args.mode.as_str() {
            "bytes" => bytes_to_policy_text(&buf[..len]),
            "corpus-mutate" => {
                // libfuzzer-style: pick a random seed, copy it, randomly
                // mutate 1-3 bytes (delete / duplicate / replace / insert).
                let seed_idx = (rng.next_u32() as usize) % SEED_CORPUS.len();
                let mut s: Vec<u8> = SEED_CORPUS[seed_idx].as_bytes().to_vec();
                let budget_n = 1 + (rng.next_u32() % 3) as usize; // 1..3
                for _ in 0..budget_n {
                    if s.is_empty() {
                        break;
                    }
                    let pos = (rng.next_u32() as usize) % s.len();
                    let op = rng.next_u32() % 4;
                    match op {
                        0 => {
                            s.remove(pos);
                        }
                        1 => {
                            let b = s[pos];
                            s.insert(pos, b);
                        }
                        2 => {
                            s[pos] = (rng.next_u32() % 0x80) as u8;
                        }
                        _ => {
                            s.insert(pos, (rng.next_u32() % 0x80) as u8);
                        }
                    }
                }
                String::from_utf8_lossy(&s).into_owned()
            }
            "arbitrary" => {
                // Reserved.  See module-level docs.  We fall back to bytes
                // mode so callers can still smoke-test the flag.
                bytes_to_policy_text(&buf[..len])
            }
            _ => {
                eprintln!("unknown mode: {}", args.mode);
                std::process::exit(2);
            }
        };

        // Track the actual byte length given to the parser (corpus-mutate
        // produces text of varying length, not the raw `len`).
        let text_len = text.len();
        total_bytes += text_len as u64;

        let attempt_start = Instant::now();
        let (parsed, evaluated, decision) =
            try_parse_and_eval(&text, &entities, &req, &authorizer);
        let elapsed_ms = attempt_start.elapsed().as_secs_f64() * 1000.0;

        if parsed {
            parsed_count += 1;
        }
        if evaluated {
            evaluated_count += 1;
            if decision == "Allow" {
                allow_count += 1;
            } else if decision == "Deny" {
                deny_count += 1;
            }
        }

        if !args.only_emit_parsed || parsed {
            println!(
                r#"{{"attempt":{},"bytes":{},"parsed":{},"evaluated":{},"decision":{:?},"elapsed_ms":{:.4}}}"#,
                attempts, text_len, parsed, evaluated, decision, elapsed_ms
            );
        }

        attempts += 1;

        if args.progress_every > 0 && attempts % args.progress_every as u64 == 0 {
            let elapsed = t0.elapsed().as_secs_f64();
            eprintln!(
                "[progress] attempts={} parsed={} evaluated={} elapsed={:.1}s rate={:.0}/s",
                attempts,
                parsed_count,
                evaluated_count,
                elapsed,
                attempts as f64 / elapsed.max(0.001)
            );
        }
    }

    let elapsed_total = t0.elapsed().as_secs_f64();
    let parse_rate = parsed_count as f64 / attempts.max(1) as f64;
    let eval_rate = evaluated_count as f64 / attempts.max(1) as f64;

    let summary = serde_json::json!({
        "summary": {
            "mode": args.mode,
            "n_attempts": attempts,
            "parsed": parsed_count,
            "evaluated": evaluated_count,
            "allow": allow_count,
            "deny": deny_count,
            "parse_reach_rate": parse_rate,
            "evaluator_reach_rate": eval_rate,
            "total_bytes_consumed": total_bytes,
            "elapsed_secs": elapsed_total,
            "attempts_per_sec": attempts as f64 / elapsed_total.max(0.001),
            "evaluator_reach_per_sec": evaluated_count as f64 / elapsed_total.max(0.001),
            "cost_per_evaluator_reach_ms": if evaluated_count == 0 {
                serde_json::Value::Null
            } else {
                serde_json::json!((elapsed_total * 1000.0) / evaluated_count as f64)
            },
            "min_byte_len": args.min_byte_len,
            "max_byte_len": args.max_byte_len,
            "seed": args.seed,
        }
    });
    println!("{}", summary);
    eprintln!(
        "[cedar_drt_replica] DONE attempts={} parsed={} evaluated={} elapsed={:.1}s",
        attempts, parsed_count, evaluated_count, elapsed_total
    );
}
