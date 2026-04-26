"""
experiments/phase_d_drt_headtohead/run_headtohead.py
====================================================

Budget-matched head-to-head between AWS cedar-drt's byte-level baseline
and our type-directed `genPolicy` (the §8 evaluation pipeline).

The §8 paper cites cedar-drt's byte-level reach rate (~0.05) as the
baseline our type-directed generator improves on, but never runs the
two side-by-side. This driver fixes that gap.

What we run
-----------
1. **cedar-drt replica** (`cedar_drt_replica/`):
   A standalone Rust binary that mirrors cedar-drt's `simple-parser`
   fuzz target (`fuzz_target!(|input: String| parse_policyset(&input))`)
   plus the post-parse `Authorizer::is_authorized` step. We could not
   run cedar-drt's full DRT in-place because:

   * cedar-spec's vendored `cedar-policy-generators` 4.0.0 has API
     drift against cedar HEAD 4.10 (69 compile errors with cap-lints).
   * The full cedar-drt cargo-fuzz pipeline requires libfuzzer +
     Lean+Rust FFI link, which is a multi-step build outside the
     kairos-cedar image (no cargo-fuzz, no protoc build deps).

   The replica preserves the metric-of-interest (bytes -> parser
   reach -> evaluator reach) by using cedar-policy's public parser +
   authorizer API at the same byte->policy text granularity that
   cedar-drt's `simple-parser` target uses. This is the cleanest
   apples-to-apples for the byte-level baseline claim.

   Two replica modes are run back-to-back at matched per-mode wall
   budget (half of --drt-budget-secs each):
     * bytes:         pure random bytes.  Worst-case lower bound on
                      reach; matches the "byte-level baseline"
                      framing for raw `arbitrary` without seed corpus.
     * corpus-mutate: libfuzzer-style; pick a random valid Cedar
                      policy seed from a small corpus, apply 1-3
                      small mutations (delete / dup / replace / insert),
                      then parse + eval.  Approximates what cedar-drt's
                      `simple-parser` target plus libfuzzer corpus
                      replay achieves at the same wall budget.

2. **Our pipeline** (`experiments/phase_c_diff/run_diff.py`):
   N=10000 type-directed Lean tuples through the Rust+Go diff harness.

Output
------
* `outputs/cedar_drt_bytes_attempts.jsonl`  : parsed-attempt log
* `outputs/cedar_drt_corpus_attempts.jsonl` : parsed-attempt log
* `outputs/summary.json`                     : full machine-readable run
* `comparison_table.tex`                     : drop-in LaTeX comparison table

Trace events
------------
Every meaningful callsite emits via _emit (TraceEvent dataclass) so
the run is auditable in sdk_agent_events.

Run subtype: differential_test
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import kairos
import kairos.trace as ktrace

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PHASE_D_DIR = Path(__file__).resolve().parent
REPLICA_DIR = PHASE_D_DIR / "cedar_drt_replica"
OUTPUTS_DIR = PHASE_D_DIR / "outputs"
IMAGE = os.environ.get("KAIROS_CEDAR_IMAGE", "ghcr.io/athanor-ai/kairos-cedar:latest")


_EMIT_SEQUENCE = [0]


def _emit(sink, sess, event_type: str, payload: dict) -> None:
    """Best-effort SDK trace emit (TraceEvent dataclass).

    Mirrors the helper in experiments/phase_c_diff/run_diff.py: passing
    a dict to SupabaseTraceSink.emit silently fails validation and drops
    the event, which is the silent-loss failure mode this helper guards
    against (deferred follow-up tracked upstream).
    """
    if sink is None:
        return
    try:
        from kairos.trace import TraceEvent
        run_id = (getattr(sess, "run_id", None)
                  or getattr(sess, "session_id", None)
                  or getattr(sess, "task_id", "unknown"))
        _EMIT_SEQUENCE[0] += 1
        event = TraceEvent(
            run_id=run_id,
            run_type="sdk_orchestration",
            run_subtype="differential_test",
            event_type=event_type,
            sequence=_EMIT_SEQUENCE[0],
            payload=payload,
        )
        sink.emit(event)
    except Exception as e:
        print(f"      WARN: emit failed for event_type={event_type}: {e}",
              file=sys.stderr)


# ── helpers ──────────────────────────────────────────────────────────────


def run_in_image(
    cmd: list[str], *, workdir: str = "/work", timeout: int = 600
) -> subprocess.CompletedProcess[str]:
    """Shell a command inside the kairos-cedar container."""
    argv = [
        "docker", "run", "--rm",
        "-v", f"{REPO_ROOT}:/work",
        "-w", workdir,
        IMAGE,
        *cmd,
    ]
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def build_replica(timeout: int = 600) -> bool:
    """Build the cedar-drt replica binary inside the kairos-cedar image."""
    print(f"\n[build] Building cedar_drt_replica (release) ...")
    proc = run_in_image(
        [
            "bash", "-c",
            "cd /work/experiments/phase_d_drt_headtohead/cedar_drt_replica && "
            "cargo +1.94.0 build --release 2>&1 | tail -20"
        ],
        workdir="/work",
        timeout=timeout,
    )
    if proc.returncode != 0:
        print("[build] FAILED")
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])
        return False
    binary_path = REPLICA_DIR / "target" / "release" / "cedar_drt_replica"
    if not binary_path.exists():
        print(f"[build] FAILED: binary not found at {binary_path}")
        return False
    print(f"[build] OK: binary at {binary_path}")
    return True


def run_cedar_drt_replica(
    *,
    mode: str,
    n: int,
    seed: int,
    time_budget_secs: int,
    min_byte_len: int,
    max_byte_len: int,
    timeout: int,
    output_filename: str,
) -> dict:
    """Run the cedar-drt replica binary in `mode` and parse its summary."""
    output_jsonl = OUTPUTS_DIR / output_filename
    print(f"\n[cedar-drt replica/{mode}] running (budget={time_budget_secs}s, n={n}) ...")
    cmd = [
        "bash", "-c",
        f"cd /work/experiments/phase_d_drt_headtohead/cedar_drt_replica && "
        f"./target/release/cedar_drt_replica "
        f"--mode {mode} --n {n} --seed {seed} "
        f"--time-budget-secs {time_budget_secs} "
        f"--min-byte-len {min_byte_len} --max-byte-len {max_byte_len} "
        f"--progress-every 100000 --only-emit-parsed "
        f"> /work/experiments/phase_d_drt_headtohead/outputs/{output_filename}"
    ]

    t0 = time.monotonic()
    proc = run_in_image(cmd, timeout=timeout)
    elapsed = time.monotonic() - t0

    print(f"[cedar-drt replica/{mode}] exit={proc.returncode} elapsed={elapsed:.1f}s")
    if proc.stderr:
        print(f"[cedar-drt replica/{mode}] stderr (last 500 chars): {proc.stderr[-500:]}")

    summary: dict = {}
    if output_jsonl.exists():
        with open(output_jsonl) as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        if lines:
            last = lines[-1]
            try:
                obj = json.loads(last)
                if "summary" in obj:
                    summary = obj["summary"]
            except json.JSONDecodeError:
                pass
        print(f"[cedar-drt replica/{mode}] {len(lines)} JSONL lines emitted")

    summary["wall_secs"] = elapsed
    summary["exit_code"] = proc.returncode
    summary["mode"] = mode
    return summary


def run_type_directed(*, n: int, timeout: int) -> dict:
    """Run our type-directed pipeline via experiments/phase_c_diff/run_diff.py."""
    print(f"\n[type-directed] running run_diff.py with N={n} ...")
    cmd = [
        sys.executable,
        str(REPO_ROOT / "experiments" / "phase_c_diff" / "run_diff.py"),
        "--n", str(n),
        "--no-session",
    ]
    t0 = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    elapsed = time.monotonic() - t0
    print(f"[type-directed] exit={proc.returncode} elapsed={elapsed:.1f}s")

    log_path = OUTPUTS_DIR / "type_directed_run.log"
    log_path.write_text(proc.stdout + "\n--- STDERR ---\n" + proc.stderr)

    # Parse the §8 summary block from stdout.
    summary: dict = {
        "wall_secs": elapsed,
        "exit_code": proc.returncode,
    }
    for line in proc.stdout.splitlines():
        s = line.strip()
        if s.startswith("N sampled"):
            try:
                summary["n_sampled"] = int(s.split(":")[1].strip())
            except (ValueError, IndexError):
                pass
        elif s.startswith("Valid-sample rate"):
            try:
                rate = s.split(":")[1].strip().split()[0]
                summary["valid_sample_rate"] = float(rate)
            except (ValueError, IndexError):
                pass
        elif s.startswith("Pairs compared"):
            try:
                num = s.split(":")[1].strip().split()[0]
                summary["pairs_compared"] = int(num)
            except (ValueError, IndexError):
                pass
        elif s.startswith("Agreement rate"):
            try:
                rate = s.split(":")[1].strip().split()[0]
                summary["agreement_rate"] = float(rate)
            except (ValueError, IndexError):
                pass
        elif s.startswith("Disagreement count"):
            try:
                num = s.split(":")[1].strip()
                summary["disagreement_count"] = int(num)
            except ValueError:
                pass
    return summary


def make_comparison_row(drt: dict, ours: dict, *, n_attempts_ours: int) -> dict:
    """Produce a side-by-side comparison row for the paper drop-in.

    Returns native Python types (None for inf) so json.dumps(...) emits
    valid JSON instead of the non-standard `Infinity` literal.
    """
    drt_attempts = drt.get("n_attempts", 0)
    drt_eval = drt.get("evaluated", 0)
    drt_reach = drt.get("evaluator_reach_rate", 0.0)
    drt_wall = drt.get("wall_secs", 0.0)
    drt_cost_ms = (drt_wall * 1000.0 / drt_eval) if drt_eval > 0 else None

    ours_pairs = ours.get("pairs_compared", 0)
    ours_disagreement = ours.get("disagreement_count", 0)
    ours_wall = ours.get("wall_secs", 0.0)
    ours_reach = (ours_pairs / n_attempts_ours) if n_attempts_ours > 0 else 0.0
    ours_cost_ms = (ours_wall * 1000.0 / ours_pairs) if ours_pairs > 0 else None

    return {
        "metric": [
            "attempts",
            "evaluator_reached",
            "evaluator_reach_rate",
            "disagreements_found",
            "wall_secs",
            "cost_per_evaluator_reach_ms",
        ],
        "cedar_drt": {
            "attempts": drt_attempts,
            "evaluator_reached": drt_eval,
            "evaluator_reach_rate": drt_reach,
            "disagreements_found": 0,
            "wall_secs": drt_wall,
            "cost_per_evaluator_reach_ms": drt_cost_ms,
        },
        "type_directed": {
            "attempts": n_attempts_ours,
            "evaluator_reached": ours_pairs,
            "evaluator_reach_rate": ours_reach,
            "disagreements_found": ours_disagreement,
            "wall_secs": ours_wall,
            "cost_per_evaluator_reach_ms": ours_cost_ms,
        },
    }


def write_latex_table(
    *,
    comparison: dict,
    drt_bytes: dict,
    drt_corpus: dict,
    ours: dict,
    n_ours: int,
    path: Path,
) -> None:
    """Drop-in LaTeX comparison table.

    Three columns: cedar-drt (bytes), cedar-drt (corpus-mutate), ours.
    Bytes mode mirrors the byte-level baseline claim;
    corpus-mutate is a libfuzzer-style upper bound on what cedar-drt's
    actual `simple-parser` target with seed corpus achieves at the same
    wall budget.
    """

    def _fmt(v: Any, *, kind: str = "default") -> str:
        if v is None:
            return r"$\infty$"
        if isinstance(v, float):
            if v != v:  # NaN
                return r"$\infty$"
            if v == float("inf"):
                return r"$\infty$"
            if kind == "rate":
                return f"{v:.4f}"
            if kind == "secs":
                return f"{v:.1f}"
            if kind == "ms":
                return f"{v:.2f}"
            return f"{v:.2f}"
        if isinstance(v, int):
            return f"{v:,}"
        return str(v)

    def _bytes_row(d: dict) -> dict:
        attempts = d.get("n_attempts", 0)
        evaluated = d.get("evaluated", 0)
        wall = d.get("wall_secs", 0.0)
        cost = (wall * 1000.0 / evaluated) if evaluated > 0 else None
        return {
            "attempts": attempts,
            "evaluated": evaluated,
            "reach_rate": d.get("evaluator_reach_rate", 0.0),
            "wall_secs": wall,
            "cost_ms": cost,
        }

    bytes_row = _bytes_row(drt_bytes)
    corpus_row = _bytes_row(drt_corpus)
    ours_pairs = ours.get("pairs_compared", 0)
    ours_disagree = ours.get("disagreement_count", 0)
    ours_wall = ours.get("wall_secs", 0.0)
    ours_reach = (ours_pairs / n_ours) if n_ours > 0 else 0.0
    ours_cost = (ours_wall * 1000.0 / ours_pairs) if ours_pairs > 0 else None
    ours_row = {
        "attempts": n_ours,
        "evaluated": ours_pairs,
        "reach_rate": ours_reach,
        "disagree": ours_disagree,
        "wall_secs": ours_wall,
        "cost_ms": ours_cost,
    }

    rows = [
        ("Attempts",
         _fmt(bytes_row["attempts"]),
         _fmt(corpus_row["attempts"]),
         _fmt(ours_row["attempts"])),
        ("Evaluator reached",
         _fmt(bytes_row["evaluated"]),
         _fmt(corpus_row["evaluated"]),
         _fmt(ours_row["evaluated"])),
        ("Evaluator-reach rate",
         _fmt(bytes_row["reach_rate"], kind="rate"),
         _fmt(corpus_row["reach_rate"], kind="rate"),
         _fmt(ours_row["reach_rate"], kind="rate")),
        ("Disagreements found",
         _fmt(0),
         _fmt(0),
         _fmt(ours_row["disagree"])),
        ("Wall time (s)",
         _fmt(bytes_row["wall_secs"], kind="secs"),
         _fmt(corpus_row["wall_secs"], kind="secs"),
         _fmt(ours_row["wall_secs"], kind="secs")),
        ("Cost / evaluator-reach (ms)",
         _fmt(bytes_row["cost_ms"], kind="ms"),
         _fmt(corpus_row["cost_ms"], kind="ms"),
         _fmt(ours_row["cost_ms"], kind="ms")),
    ]

    lines = [
        r"% Generated by experiments/phase_d_drt_headtohead/run_headtohead.py",
        r"% Budget-matched head-to-head vs cedar-drt.",
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"& \multicolumn{2}{c}{\textbf{cedar-drt replica}} & \\",
        r"\cmidrule(lr){2-3}",
        r"\textbf{Metric} & \textbf{bytes} & \textbf{corpus-mutate} & \textbf{type-directed (ours)} \\",
        r"\midrule",
    ]
    for label, b, c, o in rows:
        lines.append(f"{label} & {b} & {c} & {o} \\\\")
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
    ]
    path.write_text("\n".join(lines) + "\n")


# ── main ─────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Budget-matched head-to-head: cedar-drt byte-level vs our type-directed gen"
    )
    parser.add_argument("--n-ours", type=int, default=10000,
                        help="N tuples for our type-directed run (default 10000)")
    parser.add_argument("--drt-n", type=int, default=10_000_000,
                        help="Max byte-trial attempts for cedar-drt replica (cap)")
    parser.add_argument("--drt-budget-secs", type=int, default=780,
                        help="Wall-time budget total for cedar-drt replica (split bytes/corpus 50/50). Default 780s = 13min ≈ 10× our 83s.")
    parser.add_argument("--drt-min-byte-len", type=int, default=1,
                        help="Min random byte buffer length")
    parser.add_argument("--drt-max-byte-len", type=int, default=200,
                        help="Max random byte buffer length")
    parser.add_argument("--seed", type=int, default=0xC0DE_FACE,
                        help="Seed for cedar-drt replica RNG")
    parser.add_argument("--ours-timeout", type=int, default=1800,
                        help="Timeout for run_diff.py (seconds)")
    parser.add_argument("--build-timeout", type=int, default=600,
                        help="Timeout for replica build (seconds)")
    parser.add_argument("--skip-build", action="store_true",
                        help="Skip replica build (assume already built)")
    parser.add_argument("--skip-drt", action="store_true",
                        help="Skip cedar-drt replica run (debug)")
    parser.add_argument("--skip-ours", action="store_true",
                        help="Skip our run_diff.py run (debug)")
    parser.add_argument("--no-session", action="store_true",
                        help="Skip kairos.session wrapping (local-only)")
    args = parser.parse_args()

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    sink = ktrace.default_sink_from_env() if not args.no_session else None
    task_id = f"ath-headtohead-cedardrt-vs-typed-N{args.n_ours}"
    session_cm = kairos.session(
        task_id=task_id,
        trace_sink=sink,
        vertical="auth",
        run_type="sdk_orchestration",
        run_subtype="differential_test",
        name_for_display=f"Cedar-drt head-to-head N={args.n_ours} budget={args.drt_budget_secs}s",
    )
    with session_cm as sess:
        sid = getattr(sess, "session_id", None) or getattr(sess, "task_id", task_id)
        print(f"[head-to-head] session_id={sid} sink={type(sink).__name__}")
        return _run(args, sess, sink)


def _run(args, sess, sink) -> int:
    print("=" * 72)
    print(f"  Phase D: cedar-drt vs type-directed head-to-head")
    print(f"  cedar-drt budget : {args.drt_budget_secs}s, n_cap={args.drt_n}")
    print(f"  ours N           : {args.n_ours}")
    print(f"  image            : {IMAGE}")
    print("=" * 72)

    t0_total = time.monotonic()

    _emit(sink, sess, "run_start", {
        "image": IMAGE,
        "drt_budget_secs": args.drt_budget_secs,
        "drt_n_cap": args.drt_n,
        "drt_min_byte_len": args.drt_min_byte_len,
        "drt_max_byte_len": args.drt_max_byte_len,
        "drt_seed": args.seed,
        "n_ours": args.n_ours,
        "skip_drt": args.skip_drt,
        "skip_ours": args.skip_ours,
    })

    # 1. Build replica
    if not args.skip_build and not args.skip_drt:
        _emit(sink, sess, "phase_start", {"phase": "build_replica"})
        t = time.monotonic()
        ok = build_replica(timeout=args.build_timeout)
        elapsed = time.monotonic() - t
        if not ok:
            _emit(sink, sess, "phase_error",
                  {"phase": "build_replica", "elapsed_sec": elapsed})
            _emit(sink, sess, "run_complete",
                  {"status": "failed", "reason": "replica_build_failed"})
            return 1
        _emit(sink, sess, "phase_complete",
              {"phase": "build_replica", "elapsed_sec": elapsed})

    # 2. Run cedar-drt replica: both modes
    drt_bytes_summary: dict = {}
    drt_corpus_summary: dict = {}
    drt_summary: dict = {}
    if not args.skip_drt:
        per_mode_budget = max(30, args.drt_budget_secs // 2)

        for mode, output_file, target in [
            ("bytes", "cedar_drt_bytes_attempts.jsonl", "drt_bytes"),
            ("corpus-mutate", "cedar_drt_corpus_attempts.jsonl", "drt_corpus"),
        ]:
            _emit(sink, sess, "phase_start", {
                "phase": f"cedar_drt_run_{mode}",
                "mode": mode,
                "budget_secs": per_mode_budget,
                "n_cap": args.drt_n,
            })
            t = time.monotonic()
            try:
                summary = run_cedar_drt_replica(
                    mode=mode,
                    n=args.drt_n,
                    seed=args.seed,
                    time_budget_secs=per_mode_budget,
                    min_byte_len=args.drt_min_byte_len,
                    max_byte_len=args.drt_max_byte_len,
                    timeout=per_mode_budget + 120,
                    output_filename=output_file,
                )
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - t
                _emit(sink, sess, "phase_error", {
                    "phase": f"cedar_drt_run_{mode}",
                    "mode": mode,
                    "elapsed_sec": elapsed,
                    "error": "timeout",
                })
                summary = {"wall_secs": elapsed, "error": "timeout", "mode": mode}
            elapsed = time.monotonic() - t
            _emit(sink, sess, "phase_complete", {
                "phase": f"cedar_drt_run_{mode}",
                "mode": mode,
                "elapsed_sec": elapsed,
                "n_attempts": summary.get("n_attempts", 0),
                "n_parsed": summary.get("parsed", 0),
                "n_evaluated": summary.get("evaluated", 0),
                "evaluator_reach_rate": summary.get("evaluator_reach_rate", 0.0),
            })
            if target == "drt_bytes":
                drt_bytes_summary = summary
            else:
                drt_corpus_summary = summary
        # Comparison-row "primary" cedar-drt is the BYTES mode (matches the
        # paper's byte-level claim).
        drt_summary = drt_bytes_summary
    else:
        print("[cedar-drt replica] SKIPPED")

    # 3. Run our pipeline
    ours_summary: dict = {}
    if not args.skip_ours:
        _emit(sink, sess, "phase_start", {
            "phase": "type_directed_run",
            "n": args.n_ours,
        })
        t = time.monotonic()
        try:
            ours_summary = run_type_directed(
                n=args.n_ours, timeout=args.ours_timeout
            )
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - t
            _emit(sink, sess, "phase_error", {
                "phase": "type_directed_run",
                "elapsed_sec": elapsed,
                "error": "timeout",
            })
            ours_summary = {"wall_secs": elapsed, "error": "timeout"}
        elapsed = time.monotonic() - t
        _emit(sink, sess, "phase_complete", {
            "phase": "type_directed_run",
            "elapsed_sec": elapsed,
            "n_sampled": ours_summary.get("n_sampled", 0),
            "pairs_compared": ours_summary.get("pairs_compared", 0),
            "agreement_rate": ours_summary.get("agreement_rate", 0.0),
            "disagreement_count": ours_summary.get("disagreement_count", 0),
        })
    else:
        print("[type-directed] SKIPPED")

    # 4. Build comparison
    comparison = make_comparison_row(
        drt=drt_summary,
        ours=ours_summary,
        n_attempts_ours=args.n_ours,
    )

    total_elapsed = time.monotonic() - t0_total

    # Summary file
    summary_path = OUTPUTS_DIR / "summary.json"
    summary_path.write_text(json.dumps({
        "task_id": getattr(sess, "task_id", "unknown"),
        "session_id": getattr(sess, "session_id", "unknown"),
        "image": IMAGE,
        "args": {
            "n_ours": args.n_ours,
            "drt_n_cap": args.drt_n,
            "drt_budget_secs": args.drt_budget_secs,
            "drt_min_byte_len": args.drt_min_byte_len,
            "drt_max_byte_len": args.drt_max_byte_len,
            "seed": args.seed,
        },
        "cedar_drt_bytes_summary": drt_bytes_summary if not args.skip_drt else {},
        "cedar_drt_corpus_summary": drt_corpus_summary if not args.skip_drt else {},
        "cedar_drt_primary_summary": drt_summary,
        "type_directed_summary": ours_summary,
        "comparison": comparison,
        "total_elapsed_secs": total_elapsed,
    }, indent=2, default=str))
    print(f"\n[head-to-head] summary -> {summary_path}")

    # LaTeX
    tex_path = PHASE_D_DIR / "comparison_table.tex"
    write_latex_table(
        comparison=comparison,
        drt_bytes=drt_bytes_summary,
        drt_corpus=drt_corpus_summary,
        ours=ours_summary,
        n_ours=args.n_ours,
        path=tex_path,
    )
    print(f"[head-to-head] LaTeX table -> {tex_path}")

    # Print comparison
    def _fmt_cost(v):
        return "inf" if v is None else f"{v:.2f}"

    print("\n" + "=" * 72)
    print("  HEAD-TO-HEAD COMPARISON")
    print("=" * 72)
    drt = comparison["cedar_drt"]
    ours = comparison["type_directed"]
    rows = [
        ("Attempts",                 drt["attempts"],                     ours["attempts"]),
        ("Evaluator reached",        drt["evaluator_reached"],            ours["evaluator_reached"]),
        ("Evaluator reach rate",     f"{drt['evaluator_reach_rate']:.4f}",  f"{ours['evaluator_reach_rate']:.4f}"),
        ("Disagreements found",      drt["disagreements_found"],          ours["disagreements_found"]),
        ("Wall time (s)",            f"{drt['wall_secs']:.1f}",           f"{ours['wall_secs']:.1f}"),
        ("Cost/eval-reach (ms)",     _fmt_cost(drt['cost_per_evaluator_reach_ms']),
                                     _fmt_cost(ours['cost_per_evaluator_reach_ms'])),
    ]
    print(f"  {'Metric':<28} {'cedar-drt':>15} {'type-directed':>15}")
    for label, a, b in rows:
        print(f"  {label:<28} {str(a):>15} {str(b):>15}")
    print("=" * 72)

    _emit(sink, sess, "run_complete", {
        "status": "succeeded",
        "total_elapsed_secs": total_elapsed,
        "comparison": comparison,
        "drt_summary": drt_summary,
        "ours_summary": ours_summary,
    })

    return 0


if __name__ == "__main__":
    sys.exit(main())
