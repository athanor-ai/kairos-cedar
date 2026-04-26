// experiments/phase_d_drt_headtohead/cedar_drt_replica/src/typed_main.rs
//
// Type-directed replica binary that mirrors the cedar-drt fuzz target
// `abac-type-directed.rs` (cedar-spec/cedar-drt/fuzz/fuzz_targets/abac-type-directed.rs)
// at the same byte → input → authorizer level.
//
// The actual cedar-drt cargo-fuzz binary requires:
//   - cargo-fuzz (not in image),
//   - protoc (not in image),
//   - cedar-lean compiled + the cedar-lean-ffi link (multi-step Lean build).
//
// We bypass these by:
//   1. Driving the same `cedar_policy_generators` 4.0.0 `FuzzTargetInput<true>`
//      generator that cedar-drt's `abac-type-directed` consumes, fed bytes
//      from a deterministic ChaCha8Rng → arbitrary::Unstructured.
//      cedar-drt's libfuzzer driver does the same thing (libfuzzer is just an
//      RNG-driven Unstructured under the hood); the *generator* code path
//      executed is byte-identical to AWS's `abac-type-directed` target.
//   2. Replacing the Lean-vs-Rust diff oracle with cedar-policy's Rust
//      authorizer alone, recording reach + decision per request.  The
//      Rust-vs-Go diff is run as a separate downstream step in the Python
//      driver (mirroring our own §8 pipeline).
//
// What this measures:
//   - attempts                : number of byte-buffers consumed by the
//                               type-directed generator
//   - generator_succeeded     : Unstructured produced a valid
//                               FuzzTargetInput<true> (i.e. did not return
//                               NotEnoughData / IncorrectFormat).
//   - parsed                  : same as generator_succeeded for
//                               type-directed (the generator emits an
//                               already-typed Policy; parsing is trivially
//                               OK).  Tracked separately so the JSONL
//                               schema lines up with the bytes/corpus
//                               replica.
//   - evaluated               : per-request (8 requests per input); sums
//                               across all generated FuzzTargetInputs
//   - allow / deny / runtime  : decision counts from is_authorized
//   - disagreements           : currently 0 (we run a single Rust authorizer);
//                               cedar-go diff is computed separately by the
//                               Python driver via the existing diff oracle.
//
// Output schema matches the bytes/corpus replica so the head-to-head LaTeX
// table can use a shared `_bytes_row(d)` builder.

use std::env;
use std::time::{Duration, Instant};

use arbitrary::{Arbitrary, Unstructured};
use cedar_policy::{Authorizer, Decision, Entities, Policy, PolicySet, Schema};
use cedar_policy_generators::{
    abac::{ABACPolicy, ABACRequest},
    hierarchy::Hierarchy,
    schema::Schema as GenSchema,
    settings::ABACSettings,
};
use rand::{RngCore, SeedableRng};
use rand_chacha::ChaCha8Rng;

#[derive(Debug, Clone)]
struct Args {
    n: usize,
    seed: u64,
    time_budget_secs: u64,
    /// Bytes per Unstructured slice.  cedar-drt uses libfuzzer's default
    /// (~4096); we match.  The generator uses bounded-depth so 4096 is
    /// large enough to produce nontrivial inputs.
    bytes_per_input: usize,
    progress_every: usize,
    only_emit_parsed: bool,
}

fn parse_args() -> Args {
    let mut a = Args {
        n: 100_000,
        seed: 0xC0DE_FACE,
        time_budget_secs: 600,
        bytes_per_input: 4096,
        progress_every: 100,
        only_emit_parsed: false,
    };
    let argv: Vec<String> = env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        let s = argv[i].as_str();
        match s {
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
                a.time_budget_secs = argv[i].parse().expect("--time-budget-secs integer");
            }
            "--bytes-per-input" => {
                i += 1;
                a.bytes_per_input = argv[i].parse().expect("--bytes-per-input integer");
            }
            "--progress-every" => {
                i += 1;
                a.progress_every = argv[i].parse().expect("--progress-every integer");
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

/// Mirrors cedar-drt's `FuzzTargetInput::<TYPE_DIRECTED=true>::settings()`
/// (cedar-spec/cedar-drt/fuzz/src/abac.rs L48-L58).
fn settings() -> ABACSettings {
    ABACSettings {
        max_depth: 3,
        max_width: 3,
        ..ABACSettings::type_directed()
    }
}

/// Mirrors `FuzzTargetInput<true>::arbitrary` from
/// cedar-spec/cedar-drt/fuzz/src/abac.rs L62-L87.  Produces a
/// (schema, hierarchy/entities, policy, requests[8]) bundle.
struct TypedInput {
    cedar_schema: Schema,
    entities: Entities,
    policy: ABACPolicy,
    requests: Vec<ABACRequest>,
}

fn generate_typed_input(u: &mut Unstructured<'_>) -> arbitrary::Result<TypedInput> {
    let s = settings();
    let schema = GenSchema::arbitrary(s.clone(), u)?;
    let hierarchy = schema.arbitrary_hierarchy(u)?;
    let policy = schema.arbitrary_policy(&hierarchy, u)?;

    let requests = (0..8)
        .map(|_| schema.arbitrary_request(&hierarchy, u))
        .collect::<arbitrary::Result<Vec<_>>>()?;

    let cedar_schema: Schema = Schema::try_from(schema.clone()).map_err(|_| arbitrary::Error::IncorrectFormat)?;

    // Build entities from the hierarchy.  cedar-drt does:
    //   let all_entities = Entities::try_from(hierarchy)?;
    //   let entities = drop_some_entities(all_entities, u)?;
    //   let entities = schemas::add_actions_to_entities(&cedar_schema, entities)?;
    // We skip the random "drop_some_entities" step (it adds no signal for
    // reach-rate) and add action entities so requests can resolve.
    let all_entities: Entities = match Entities::try_from(hierarchy) {
        Ok(e) => e,
        Err(_) => return Err(arbitrary::Error::IncorrectFormat),
    };
    // Add action entities so the request action UID resolves.
    let action_entities = match cedar_schema.action_entities() {
        Ok(a) => a,
        Err(_) => return Err(arbitrary::Error::IncorrectFormat),
    };
    let entities = match all_entities.add_entities(action_entities, None) {
        Ok(e) => e,
        Err(_) => return Err(arbitrary::Error::IncorrectFormat),
    };

    Ok(TypedInput { cedar_schema, entities, policy, requests })
}

fn main() {
    let args = parse_args();
    eprintln!(
        "[cedar_drt_typed_replica] mode=abac-type-directed n={} seed={} time_budget_secs={} bytes_per_input={}",
        args.n, args.seed, args.time_budget_secs, args.bytes_per_input
    );
    eprintln!(
        "[cedar_drt_typed_replica] generator: cedar_policy_generators::abac::FuzzTargetInput<TYPE_DIRECTED=true> @ cedar-policy-generators 4.0.0"
    );

    let authorizer = Authorizer::new();

    let mut rng = ChaCha8Rng::seed_from_u64(args.seed);
    let mut buf = vec![0u8; args.bytes_per_input];

    let t0 = Instant::now();
    let budget = Duration::from_secs(args.time_budget_secs);

    let mut attempts: u64 = 0;
    let mut gen_succeeded: u64 = 0;
    let mut gen_failed_not_enough: u64 = 0;
    let mut gen_failed_other: u64 = 0;
    let mut policyset_build_failed: u64 = 0;
    let mut requests_evaluated: u64 = 0;
    let mut allow_count: u64 = 0;
    let mut deny_count: u64 = 0;
    let mut runtime_err_count: u64 = 0;
    let mut total_bytes: u64 = 0;

    while attempts < args.n as u64 {
        if t0.elapsed() >= budget {
            eprintln!(
                "[cedar_drt_typed_replica] time budget exhausted at attempt {}",
                attempts
            );
            break;
        }

        rng.fill_bytes(&mut buf);
        total_bytes += args.bytes_per_input as u64;

        let mut u = Unstructured::new(&buf);

        let attempt_start = Instant::now();
        let result = generate_typed_input(&mut u);

        match result {
            Ok(input) => {
                gen_succeeded += 1;

                // Build a PolicySet: type-directed gen always produces a
                // single valid policy, but be defensive.
                let mut pset = PolicySet::new();
                let policy: Policy = input.policy.into();
                if pset.add(policy).is_err() {
                    policyset_build_failed += 1;
                    let elapsed_ms = attempt_start.elapsed().as_secs_f64() * 1000.0;
                    if !args.only_emit_parsed {
                        println!(
                            r#"{{"attempt":{},"bytes":{},"parsed":false,"evaluated":false,"decision":"PolicySetBuildError","elapsed_ms":{:.4}}}"#,
                            attempts, args.bytes_per_input, elapsed_ms
                        );
                    }
                    attempts += 1;
                    continue;
                }

                // Each FuzzTargetInput carries 8 requests; mirror cedar-drt
                // which calls run_auth_test in a loop.
                for abac_req in input.requests.iter() {
                    let req: cedar_policy::Request = abac_req.clone().into();
                    let resp = authorizer.is_authorized(&req, &pset, &input.entities);
                    requests_evaluated += 1;
                    let dec_str = match resp.decision() {
                        Decision::Allow => {
                            allow_count += 1;
                            "Allow"
                        }
                        Decision::Deny => {
                            // Distinguish errors-during-eval (residual diags)
                            // from a clean Deny.  cedar-drt counts both as
                            // reaching the evaluator; we follow that convention.
                            if !resp.diagnostics().errors().count_eq_zero() {
                                runtime_err_count += 1;
                            }
                            deny_count += 1;
                            "Deny"
                        }
                    };

                    if !args.only_emit_parsed || true {
                        let elapsed_ms = attempt_start.elapsed().as_secs_f64() * 1000.0;
                        println!(
                            r#"{{"attempt":{},"bytes":{},"parsed":true,"evaluated":true,"decision":{:?},"elapsed_ms":{:.4}}}"#,
                            attempts, args.bytes_per_input, dec_str, elapsed_ms
                        );
                    }
                }
            }
            Err(arbitrary::Error::NotEnoughData) => {
                gen_failed_not_enough += 1;
                if !args.only_emit_parsed {
                    let elapsed_ms = attempt_start.elapsed().as_secs_f64() * 1000.0;
                    println!(
                        r#"{{"attempt":{},"bytes":{},"parsed":false,"evaluated":false,"decision":"NotEnoughData","elapsed_ms":{:.4}}}"#,
                        attempts, args.bytes_per_input, elapsed_ms
                    );
                }
            }
            Err(_) => {
                gen_failed_other += 1;
                if !args.only_emit_parsed {
                    let elapsed_ms = attempt_start.elapsed().as_secs_f64() * 1000.0;
                    println!(
                        r#"{{"attempt":{},"bytes":{},"parsed":false,"evaluated":false,"decision":"GeneratorError","elapsed_ms":{:.4}}}"#,
                        attempts, args.bytes_per_input, elapsed_ms
                    );
                }
            }
        }

        attempts += 1;

        if args.progress_every > 0 && attempts % args.progress_every as u64 == 0 {
            let elapsed = t0.elapsed().as_secs_f64();
            eprintln!(
                "[progress] attempts={} generated={} eval-requests={} elapsed={:.1}s rate={:.1}/s",
                attempts,
                gen_succeeded,
                requests_evaluated,
                elapsed,
                attempts as f64 / elapsed.max(0.001)
            );
        }
    }

    let elapsed_total = t0.elapsed().as_secs_f64();

    // Reach-rate semantics for the head-to-head table:
    //   - "parsed" maps to gen_succeeded (the type-directed generator
    //     produced a syntactically valid policy + schema + entities tuple)
    //   - "evaluated" maps to gen_succeeded * 8 (one per request).  We
    //     report the per-request count to keep the units comparable to
    //     the bytes/corpus replicas, which evaluate one fixed request per
    //     attempt.
    let parsed_count = gen_succeeded;
    let evaluated_count = requests_evaluated;
    let parse_rate = parsed_count as f64 / attempts.max(1) as f64;
    let eval_rate = evaluated_count as f64 / attempts.max(1) as f64;

    let summary = serde_json::json!({
        "summary": {
            "mode": "abac-type-directed",
            "n_attempts": attempts,
            "parsed": parsed_count,
            "evaluated": evaluated_count,
            "allow": allow_count,
            "deny": deny_count,
            "runtime_err": runtime_err_count,
            "parse_reach_rate": parse_rate,
            "evaluator_reach_rate": eval_rate,
            "gen_succeeded": gen_succeeded,
            "gen_failed_not_enough_data": gen_failed_not_enough,
            "gen_failed_other": gen_failed_other,
            "policyset_build_failed": policyset_build_failed,
            "total_bytes_consumed": total_bytes,
            "elapsed_secs": elapsed_total,
            "attempts_per_sec": attempts as f64 / elapsed_total.max(0.001),
            "evaluator_reach_per_sec": evaluated_count as f64 / elapsed_total.max(0.001),
            "cost_per_evaluator_reach_ms": if evaluated_count == 0 {
                serde_json::Value::Null
            } else {
                serde_json::json!((elapsed_total * 1000.0) / evaluated_count as f64)
            },
            "bytes_per_input": args.bytes_per_input,
            "seed": args.seed,
            "settings": {
                "match_types": true,
                "max_depth": 3,
                "max_width": 3,
                "source": "cedar_policy_generators 4.0.0 ABACSettings::type_directed() with depth/width clamp from cedar-drt fuzz/src/abac.rs L48-L58",
            },
        }
    });
    println!("{}", summary);
    eprintln!(
        "[cedar_drt_typed_replica] DONE attempts={} gen_ok={} eval_requests={} elapsed={:.1}s",
        attempts, gen_succeeded, requests_evaluated, elapsed_total
    );
}

// Helper: response.diagnostics().errors() is an Iterator; we just need to
// know if it's nonempty.  The trait we need ships in `cedar-policy` 4.10
// but the convenience method is named differently across versions; do it
// by hand.
trait DiagCount {
    fn count_eq_zero(self) -> bool;
}

impl<I: Iterator> DiagCount for I {
    fn count_eq_zero(mut self) -> bool {
        self.next().is_none()
    }
}
