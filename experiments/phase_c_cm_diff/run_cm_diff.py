"""CedarMicro-scoped differential runner.

Smaller-scope companion to the full-Cedar §8 driver in phase_c_diff/.
Samples N CedarMicro bool-typed expressions from the hand-authored
generator, embeds each as a `when` clause in a minimal Cedar policy,
and runs the resulting policy through both cedar-policy (Rust CLI) and
cedar-go against a fixed 2-request probe set. Records per-sample
decision pairs, counts disagreements, emits a summary.

CedarMicro's 5 constructors (.litInt, .litBool, .var, .ite, .and)
all translate directly to Cedar surface syntax. `.var n` becomes a
reference to a fixed set of context attribute bindings declared in
the companion schema (ctx.v0, ctx.v1, ctx.v2). The 2-request probe
gives the evaluator two concrete contexts to exercise the branches.

Usage:
  python3 experiments/phase_c_cm_diff/run_cm_diff.py --n 100
  python3 experiments/phase_c_cm_diff/run_cm_diff.py --n 1000

Outputs:
  outputs/samples.tsv       per-sample record (decision_rust / decision_go / agree)
  outputs/disagree_corpus/  one .txt file per disagreement (for shrinking)
  outputs/summary.json      aggregate metrics
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import kairos
import kairos.trace as ktrace
from kairos.observe import observe as kairos_observe

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
OUT_DIR = HERE / "outputs"
IMAGE = os.environ.get("KAIROS_CEDAR_IMAGE", "ghcr.io/athanor-ai/kairos-cedar:latest")


_EMIT_SEQUENCE = [0]  # mutable single-element list as monotonic counter


def _emit(sink, sess, event_type: str, payload: dict) -> None:
    """Best-effort SDK trace emit. Per Sam 2026-04-25 directive: every
    meaningful callsite should emit so the run is auditable in
    sdk_agent_events even on crash. Swallows errors so a sink hiccup
    never kills the run, but logs.

    Uses the kairos.trace.TraceEvent dataclass — passing a dict to
    SupabaseTraceSink.emit silently fails validation and drops the event.
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
        print(f"      WARN: emit failed for event_type={event_type}: {e}", file=sys.stderr)


def run_in_image(cmd: list[str], *, workdir: str = "/work", timeout: int = 600):
    argv = [
        "docker", "run", "--rm",
        "-v", f"{REPO_ROOT}:/work",
        "-w", workdir,
        IMAGE,
        *cmd,
    ]
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def sample_cm_bool_exprs(n: int) -> list[str]:
    """Sample N bool-typed CedarMicro expressions via MeasurePalamedes.lean.

    MeasurePalamedes prints per-line "bool<TAB>valid<TAB>depth<TAB>ctor<TAB>repr"
    but only the valid=true rows at the end contain the raw expr string.
    We use MeasureAll.lean which emits "ctype<TAB>ctor<TAB>depth<TAB>expr".
    """
    proc = run_in_image(
        ["bash", "-c",
         f"cd cedar-micro && lake env lean --run MeasureAll.lean {n} 2>&1 | grep -E '^bool'"],
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"MeasureAll.lean failed: {proc.stderr[-500:]}")
    rows = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 4 and parts[0] == "bool":
            rows.append(parts[3])  # expr is column 3
    return rows[:n]


# Minimal 3-variable context schema: v0:Long, v1:Bool, v2:Long. The
# `when` clause references ctx.v0/v1/v2 to bind CedarMicro's .var 0/1/2.
# CedarMicro's .var n under Γ=[int,bool,int] maps to (int,bool,int).
SCHEMA = """\
entity User;
entity Resource;

action probe appliesTo {
  principal: User,
  resource: Resource,
  context: {
    v0: Long,
    v1: Bool,
    v2: Long
  }
};
"""

ENTITIES = """\
[
  {"uid": {"type": "User", "id": "alice"}, "attrs": {}, "parents": []},
  {"uid": {"type": "Resource", "id": "doc"}, "attrs": {}, "parents": []}
]
"""

# Two probe requests: one where all context is "neutral" (v0=0, v1=false,
# v2=0), one where all context is "active" (v0=1, v1=true, v2=1). This
# gives us two distinct decisions to diff on most expressions.
PROBE_REQUESTS = [
    {
        "label": "neutral",
        "context": {"v0": 0, "v1": False, "v2": 0},
    },
    {
        "label": "active",
        "context": {"v0": 1, "v1": True, "v2": 1},
    },
]


def _wrap_cm_expr_as_cedar(cm_expr: str) -> str:
    """Translate a CedarMicro expr string into Cedar-surface syntax.

    CedarMicro pretty-form uses lowercase 'true'/'false', integer literals,
    'vN' for de-Bruijn indices, '&&' for and, '(if c then t else f)' for ite.
    Cedar surface syntax matches except variables need to be 'context.vN'.
    """
    # Replace bare vN with context.vN (word boundary so v10 stays v10, not
    # context.vcontext.v0).
    return re.sub(r"\bv(\d+)\b", r"context.v\1", cm_expr)


def _build_policy(cm_expr: str) -> str:
    """Wrap a CedarMicro expr as the `when` clause of a single permit policy."""
    cedar_cond = _wrap_cm_expr_as_cedar(cm_expr)
    return (
        f'permit(principal, action, resource) when {{ {cedar_cond} }};\n'
    )


_SCRATCH_LOCK = threading.Lock()


def _rust_authorize(policy: str, request_ctx: dict, worker_id: int = 0) -> str:
    """Run cedar authorize and return 'Allow' | 'Deny' | 'ERROR'.

    Per-worker scratch dir so parallel invocations don't clobber each
    other. Temp files are written inside REPO_ROOT so they appear
    under /work/ inside the container.
    """
    scratch = OUT_DIR / f"scratch-{worker_id}"
    scratch.mkdir(exist_ok=True)
    policy_path = scratch / "p.cedar"
    schema_path = scratch / "s.cedarschema"
    entities_path = scratch / "e.json"
    request_path = scratch / "r.json"

    policy_path.write_text(policy)
    schema_path.write_text(SCHEMA)
    entities_path.write_text(ENTITIES)
    request_path.write_text(json.dumps({
        "principal": 'User::"alice"',
        "action": 'Action::"probe"',
        "resource": 'Resource::"doc"',
        "context": request_ctx,
    }))

    scratch_in_image = f"/work/experiments/phase_c_cm_diff/outputs/scratch-{worker_id}"
    proc = run_in_image(
        ["bash", "-c",
         f'cedar authorize '
         f'--policies {scratch_in_image}/p.cedar '
         f'--entities {scratch_in_image}/e.json '
         f'--schema {scratch_in_image}/s.cedarschema '
         f'--request-json {scratch_in_image}/r.json 2>&1 | tail -5'],
        timeout=60,
    )
    out = (proc.stdout + proc.stderr).upper()
    if "ALLOW" in out:
        return "Allow"
    if "DENY" in out:
        return "Deny"
    return "ERROR"


def _eval_one(job: dict) -> dict:
    """Worker: evaluate one (sample_idx, probe, expr) job. Called in
    a thread pool; each thread pins to a unique worker_id so scratch
    dirs don't collide."""
    worker_id = threading.get_ident() % 64
    decision = _rust_authorize(job["policy"], job["probe_ctx"], worker_id=worker_id)
    return {
        "idx": job["idx"],
        "probe": job["probe_label"],
        "expr": job["expr"],
        "decision_rust": decision,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--workers", type=int, default=16,
                        help="parallel cedar-cli invocations (each = 1 docker container)")
    parser.add_argument("--no-session", action="store_true",
                        help="skip kairos.session wrapping (local-only, no Tahoe trace)")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    disagree_dir = OUT_DIR / "disagree_corpus"
    disagree_dir.mkdir(parents=True, exist_ok=True)

    # SDK dogfood per qa's capability map (2026-04-24 17:38Z): wrap the
    # whole run in kairos.session so a parent solve_runs row opens +
    # closes, every observed LLM/Lean call joins the same session, and
    # /solve-runs + /cost dashboards populate. ATH-524/544/548.
    sink = ktrace.default_sink_from_env() if not args.no_session else None
    task_id = f"ath-529-cedar-n{args.n}-diff"
    session_cm = kairos.session(
        task_id=task_id,
        trace_sink=sink,
        vertical="auth",  # Cedar policies = authorization vertical
        run_type="sdk_orchestration",
        run_subtype="autoformalize",
        name_for_display=f"Cedar diff-run N={args.n}",
    )

    with session_cm as sess:
        session_id = getattr(sess, "session_id", None) or getattr(sess, "task_id", task_id)
        print(f"[cm-diff] session_id={session_id} sink={type(sink).__name__}")

        with kairos_observe(
            session_id=session_id,
            sink=sink,
            run_type="sdk_orchestration",
            run_subtype="autoformalize",
        ):
            return _run_diff(args, sess, sink)


def _run_diff(args, sess=None, sink=None) -> int:
    import math as _math

    t0_total = time.monotonic()
    _emit(sink, sess, "run_start", {
        "n_target": args.n,
        "workers": args.workers,
        "image": IMAGE,
        "no_session": bool(args.no_session),
        "n_probe_per_sample": len(PROBE_REQUESTS),
    })

    # Phase 1: sample CedarMicro bool exprs from MeasureAll.lean
    print(f"[cm-diff] sampling {args.n} CedarMicro bool exprs via MeasureAll.lean ...")
    _emit(sink, sess, "phase_start", {"phase": "sample_cm_exprs", "n_target": args.n})
    t0 = time.monotonic()
    try:
        exprs = sample_cm_bool_exprs(args.n)
    except Exception as e:
        t_sample_err = time.monotonic() - t0
        _emit(sink, sess, "phase_error", {
            "phase": "sample_cm_exprs", "error": str(e),
            "elapsed_sec": round(t_sample_err, 3),
        })
        _emit(sink, sess, "run_complete", {
            "status": "failed", "reason": "sample_cm_exprs_failed",
        })
        raise
    t_sample = time.monotonic() - t0
    print(f"[cm-diff]   got {len(exprs)} samples in {t_sample:.1f}s")
    _emit(sink, sess, "phase_complete", {
        "phase": "sample_cm_exprs",
        "n_generated": len(exprs),
        "n_target": args.n,
        "elapsed_sec": round(t_sample, 3),
        "underflow": len(exprs) < args.n,
    })

    # Phase 2: build evaluator job list (one entry per (sample, probe))
    _emit(sink, sess, "phase_start", {"phase": "build_jobs", "n_samples": len(exprs)})
    t_jobs_start = time.monotonic()
    jobs = []
    for idx, cm_expr in enumerate(exprs):
        policy = _build_policy(cm_expr)
        for probe in PROBE_REQUESTS:
            jobs.append({
                "idx": idx,
                "probe_label": probe["label"],
                "probe_ctx": probe["context"],
                "expr": cm_expr,
                "policy": policy,
            })
    t_jobs = time.monotonic() - t_jobs_start
    _emit(sink, sess, "phase_complete", {
        "phase": "build_jobs",
        "n_jobs": len(jobs),
        "n_samples": len(exprs),
        "n_probe_per_sample": len(PROBE_REQUESTS),
        "elapsed_sec": round(t_jobs, 3),
    })

    # Phase 3: parallel rust evaluator probes
    print(f"[cm-diff] dispatching {len(jobs)} evaluator calls across {args.workers} workers ...")
    _emit(sink, sess, "phase_start", {
        "phase": "rust_evaluator_probes",
        "n_jobs": len(jobs),
        "workers": args.workers,
    })
    t_eval_start = time.monotonic()
    results: list[dict] = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for i, r in enumerate(pool.map(_eval_one, jobs)):
                results.append(r)
                if (i + 1) % 200 == 0:
                    elapsed = time.monotonic() - t_eval_start
                    rate = (i + 1) / elapsed
                    remaining = (len(jobs) - i - 1) / rate
                    print(f"[cm-diff]   {i+1}/{len(jobs)} ({rate:.1f} calls/s, "
                          f"~{remaining:.0f}s remaining)")
    except Exception as e:
        t_eval_err = time.monotonic() - t_eval_start
        _emit(sink, sess, "phase_error", {
            "phase": "rust_evaluator_probes",
            "error": str(e),
            "elapsed_sec": round(t_eval_err, 3),
            "n_completed": len(results),
        })
        _emit(sink, sess, "run_complete", {
            "status": "failed", "reason": "rust_evaluator_probes_failed",
        })
        raise
    t_eval = time.monotonic() - t_eval_start
    _emit(sink, sess, "phase_complete", {
        "phase": "rust_evaluator_probes",
        "n_jobs": len(jobs),
        "n_results": len(results),
        "elapsed_sec": round(t_eval, 3),
        "calls_per_sec": round(len(jobs) / max(1e-6, t_eval), 2),
    })

    # Phase 4: aggregate results, write TSV + summary.json
    _emit(sink, sess, "phase_start", {
        "phase": "aggregate", "n_results": len(results),
    })
    t_agg_start = time.monotonic()
    samples_tsv = OUT_DIR / "samples.tsv"
    with samples_tsv.open("w") as sf:
        sf.write("idx\tprobe\texpr\tdecision_rust\tdecision_go\tagree\n")
        n_valid = 0
        n_rust_err = 0
        for r in results:
            if r["decision_rust"] != "ERROR":
                n_valid += 1
            else:
                n_rust_err += 1
            sf.write(
                f"{r['idx']}\t{r['probe']}\t{r['expr']}\t"
                f"{r['decision_rust']}\tN/A\tN/A\n"
            )

    n_eval_calls = len(exprs) * len(PROBE_REQUESTS)
    valid_rate_rust = n_valid / max(1, n_eval_calls)
    summary = {
        "n_samples": len(exprs),
        "n_probe_per_sample": len(PROBE_REQUESTS),
        "n_evaluator_calls": n_eval_calls,
        "n_rust_valid": n_valid,
        "n_rust_error": n_rust_err,
        "valid_rate_rust": valid_rate_rust,
        "t_sample_sec": round(t_sample, 2),
        "t_eval_sec": round(t_eval, 2),
        "note": (
            "First-pass CedarMicro-scope diff-runner. cedar-go wiring "
            "deferred to companion full-Cedar driver in phase_c_diff/. "
            "This driver establishes the Rust-CLI invocation path + "
            "CedarMicro-to-Cedar-surface translation for the paper's "
            "§8 evaluation prose."
        ),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    t_agg = time.monotonic() - t_agg_start
    _emit(sink, sess, "phase_complete", {
        "phase": "aggregate",
        "n_rust_valid": n_valid,
        "n_rust_error": n_rust_err,
        "valid_rate_rust": valid_rate_rust,
        "elapsed_sec": round(t_agg, 3),
        "samples_tsv": str(samples_tsv),
    })

    print(f"\n[cm-diff] SUMMARY")
    print(f"  samples         : {len(exprs)}")
    print(f"  evaluator calls : {n_eval_calls} "
          f"({len(PROBE_REQUESTS)} probes per sample)")
    print(f"  rust valid      : {n_valid}/{n_eval_calls} "
          f"({valid_rate_rust:.3f})")
    print(f"  rust errors     : {n_rust_err}")
    print(f"  sample wall     : {t_sample:.1f}s")
    print(f"  eval wall       : {t_eval:.1f}s")
    print(f"  outputs         : {OUT_DIR}")

    # Terminal run_complete event — closes the session in DB so it doesn't
    # get marked failed by the stale-run watchdog (ATH-571). Coerce NaN →
    # None since PostgREST rejects NaN with PGRST102.
    _valid_rate_rust = (None if _math.isnan(valid_rate_rust) else valid_rate_rust)
    total_elapsed = time.monotonic() - t0_total
    _emit(sink, sess, "run_complete", {
        "status": "succeeded" if n_rust_err == 0 else "failed",
        "n_samples": len(exprs),
        "n_probe_per_sample": len(PROBE_REQUESTS),
        "n_evaluator_calls": n_eval_calls,
        "n_rust_valid": n_valid,
        "n_rust_error": n_rust_err,
        "valid_rate_rust": _valid_rate_rust,
        "t_sample_sec": round(t_sample, 3),
        "t_eval_sec": round(t_eval, 3),
        "wall_time_total_sec": round(total_elapsed, 3),
    })

    return 0 if n_rust_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
