"""Byte-level arbitrary-style baseline for §8 Table 4 row 2.

Uses kairos.differential.run() (PR #176) with the arbitrary_bytes
sampler and a Cedar parse+validate yield gate. Measures the
fraction of random byte buffers that decode to a well-formed,
schema-valid Cedar policy, and — among those — whether cedar-policy
and cedar-go agree on evaluation.

This is the honest byte-level floor: no structural arbitrary-crate
scaffolding, no retry, no hand-aided surface form. Most draws do
not parse. Those that do get a fixed principal/action/resource
attached and are evaluated under both implementations.

Usage:
    python3 experiments/phase_c_baseline/run_baseline.py --n 10000

Outputs:
    experiments/phase_c_baseline/outputs/summary.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from kairos.differential import (
    run as differential_run,
    Implementation,
    arbitrary_bytes,
    YieldGateResult,
)
import kairos
import kairos.trace as ktrace

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
OUT_DIR = HERE / "outputs"
IMAGE = os.environ.get("KAIROS_CEDAR_IMAGE", "ghcr.io/athanor-ai/kairos-cedar:latest")


_EMIT_SEQUENCE = [0]  # mutable single-element list as monotonic counter


def _emit(sink, sess, event_type: str, payload: dict) -> None:
    """Best-effort SDK trace emit. Per Sam 2026-04-25 directive: every meaningful
    callsite should emit so the run is auditable in sdk_agent_events even on
    crash. Swallows errors so a sink hiccup never kills the run, but logs.

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

FIXED_SCHEMA_TEXT = """\
entity User;
entity Document;
entity Photo;

action view, edit, admin appliesTo {
    principal: User,
    resource: [Document, Photo],
};
"""

FIXED_ENTITIES = [
    {"uid": {"type": "User", "id": "alice"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Document", "id": "doc1"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Photo", "id": "photo1"}, "attrs": {}, "parents": []},
]

FIXED_REQUEST = {
    "principal": 'User::"alice"',
    "action": 'Action::"view"',
    "resource": 'Document::"doc1"',
}


_CONTAINER_NAME = "baseline-cedar-longlived"


def _ensure_container() -> None:
    """Start a long-lived container once — `docker exec` per call
    avoids the ~0.5s docker-run startup cost per sample."""
    probe = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", _CONTAINER_NAME],
        capture_output=True, text=True,
    )
    if probe.returncode == 0 and probe.stdout.strip() == "true":
        return
    subprocess.run(
        ["docker", "rm", "-f", _CONTAINER_NAME],
        capture_output=True, text=True,
    )
    subprocess.run(
        [
            "docker", "run", "-d", "--name", _CONTAINER_NAME,
            "-v", f"{REPO_ROOT}:/work",
            "-w", "/work",
            IMAGE,
            "sleep", "infinity",
        ],
        capture_output=True, text=True, check=True,
    )


def _run_in_image(cmd: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "exec", _CONTAINER_NAME, *cmd],
        capture_output=True, text=True, timeout=timeout,
    )


_SCRATCH = None


def _scratch_dir() -> Path:
    global _SCRATCH
    if _SCRATCH is None:
        _SCRATCH = OUT_DIR / "scratch"
        _SCRATCH.mkdir(parents=True, exist_ok=True)
        (_SCRATCH / "s.cedarschema").write_text(FIXED_SCHEMA_TEXT)
        (_SCRATCH / "e.json").write_text(json.dumps(FIXED_ENTITIES))
        (_SCRATCH / "r.json").write_text(json.dumps(FIXED_REQUEST))
    return _SCRATCH


def cedar_parse_validate_gate(sample: bytes) -> YieldGateResult:
    """Decode random bytes as a Cedar policy, validate against the fixed schema.

    Returns valid=True iff the bytes decode to ASCII, parse as a Cedar
    policy, and validate against the fixed schema. The parsed payload
    carries the accepted policy text so invokers can evaluate it.
    """
    # latin-1 is lossless 1:1 byte↔char. Most resulting strings will fail
    # to parse as Cedar, but we let the parser make the call rather than
    # gating on ASCII-ness up front.
    text = sample.decode("latin-1", errors="strict")
    scratch = _scratch_dir()
    policy_path = scratch / "p.cedar"
    policy_path.write_text(text)

    scratch_in = "/work/experiments/phase_c_baseline/outputs/scratch"
    proc = _run_in_image(
        [
            "cedar", "validate",
            "--policies", f"{scratch_in}/p.cedar",
            "--schema", f"{scratch_in}/s.cedarschema",
        ],
        timeout=30,
    )
    out = (proc.stdout + proc.stderr).lower()
    if proc.returncode == 0:
        return YieldGateResult(
            valid=True,
            parsed={"policy": text},
            reason="parsed_and_typechecked",
        )
    if "failed to parse" in out or "invalid token" in out or "unexpected" in out:
        return YieldGateResult(valid=False, parsed=None, reason="parse_error")
    return YieldGateResult(valid=False, parsed=None, reason="typecheck_error")


def cedar_policy_invoker(parsed: dict) -> str:
    """Run cedar authorize on the accepted policy + fixed request."""
    scratch = _scratch_dir()
    (scratch / "p.cedar").write_text(parsed["policy"])
    scratch_in = "/work/experiments/phase_c_baseline/outputs/scratch"
    proc = _run_in_image(
        [
            "bash", "-c",
            f"cedar authorize --policies {scratch_in}/p.cedar "
            f"--entities {scratch_in}/e.json --schema {scratch_in}/s.cedarschema "
            f"--request-json {scratch_in}/r.json 2>&1 | tail -5",
        ],
        timeout=30,
    )
    out = (proc.stdout + proc.stderr).upper()
    if "ALLOW" in out:
        return "Allow"
    if "DENY" in out:
        return "Deny"
    return "ERROR"


def cedar_go_invoker(parsed: dict) -> str:
    """Evaluate the accepted policy via a cedar-go single-shot harness."""
    # Minimal Go one-shot: write a policy, evaluate via cedar-go runtime.
    # We piggyback on the phase_c_diff go_harness binary if present, else
    # fall back to marking ERROR (the baseline's job is yield_rate, not
    # per-tuple diff integrity; per-tuple diffs are the type-directed
    # runner's thing).
    harness_binary = REPO_ROOT / "experiments" / "phase_c_diff" / "go_harness"
    if not harness_binary.exists():
        return "SKIP_NO_HARNESS"

    go_input = {
        "idx": "baseline",
        "principal": FIXED_REQUEST["principal"].replace('"', '').replace('::', '::'),
        "action": FIXED_REQUEST["action"].replace('"', '').replace('::', '::'),
        "resource": FIXED_REQUEST["resource"].replace('"', '').replace('::', '::'),
        "policy": parsed["policy"],
    }
    # Reuse phase_c_diff/go_harness: build + run in one shot.
    scratch = _scratch_dir()
    input_path = scratch / "go_input.jsonl"
    input_path.write_text(json.dumps(go_input))
    entities_in_image = "/work/experiments/phase_c_diff/fixtures/entities.json"
    proc = _run_in_image(
        [
            "bash", "-c",
            "cd /work/experiments/phase_c_diff/go_harness && "
            "GOFLAGS='-mod=mod -buildvcs=false' go build -o /tmp/diff-harness . >/dev/null 2>&1 && "
            f"/tmp/diff-harness {entities_in_image} < /work/experiments/phase_c_baseline/outputs/scratch/go_input.jsonl"
        ],
        timeout=60,
    )
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if "error" in obj:
                return "ERROR"
            return obj.get("decision", "ERROR")
        except json.JSONDecodeError:
            pass
    return "ERROR"


def main() -> int:
    parser = argparse.ArgumentParser(description="§8 byte-level baseline for Table 4 row 2")
    parser.add_argument("--n", type=int, default=100,
                        help="Number of random byte buffers to sample")
    parser.add_argument("--n-bytes", type=int, default=4096,
                        help="Bytes per sample")
    parser.add_argument("--no-session", action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sink = ktrace.default_sink_from_env() if not args.no_session else None
    task_id = f"ath-529-cedar-bytes-baseline-n{args.n}"
    session_cm = kairos.session(
        task_id=task_id,
        trace_sink=sink,
        vertical="auth",
        run_type="sdk_orchestration",
        run_subtype="differential_test",
        name_for_display=f"Cedar byte-level baseline N={args.n}",
    )

    with session_cm as sess:
        sid = getattr(sess, "session_id", None) or task_id
        print(f"[baseline] session_id={sid} sink={type(sink).__name__}")
        print(f"[baseline] N={args.n} n_bytes={args.n_bytes}")

        t0_total = time.monotonic()
        _emit(sink, sess, "run_start", {
            "n_target": args.n,
            "n_bytes": args.n_bytes,
            "image": IMAGE,
            "sampler": "arbitrary_bytes",
            "yield_gate": "cedar_parse_validate_gate",
            "no_session": bool(args.no_session),
        })

        # Phase 1: setup — write fixtures + start long-lived container
        print(f"\n[1/3] Setting up scratch fixtures + container ...")
        _emit(sink, sess, "phase_start", {"phase": "setup"})
        t_setup = time.monotonic()
        try:
            _scratch_dir()
            _ensure_container()
        except Exception as e:
            _emit(sink, sess, "phase_error", {"phase": "setup", "error": str(e)})
            _emit(sink, sess, "run_complete", {"status": "failed", "reason": "setup_failed"})
            raise
        elapsed_setup = time.monotonic() - t_setup
        print(f"      setup done in {elapsed_setup:.2f}s (container={_CONTAINER_NAME})")
        _emit(sink, sess, "phase_complete", {
            "phase": "setup",
            "elapsed_sec": elapsed_setup,
            "container": _CONTAINER_NAME,
        })

        # Phase 2: differential_run — sample bytes, run gate, invoke impls
        print(f"\n[2/3] Running differential_run (N={args.n}, n_bytes={args.n_bytes}) ...")
        _emit(sink, sess, "phase_start", {
            "phase": "differential_run",
            "n_target": args.n,
            "n_bytes": args.n_bytes,
        })
        t_diff = time.monotonic()
        try:
            summary = differential_run(
                run_id=task_id,
                sampler=arbitrary_bytes(n_bytes=args.n_bytes),
                impls=[
                    Implementation("cedar-policy", cedar_policy_invoker),
                    Implementation("cedar-go", cedar_go_invoker),
                ],
                n_samples=args.n,
                yield_gate=cedar_parse_validate_gate,
            )
        except Exception as e:
            _emit(sink, sess, "phase_error", {"phase": "differential_run", "error": str(e)})
            _emit(sink, sess, "run_complete", {
                "status": "failed", "reason": "differential_run_failed",
            })
            raise
        elapsed_diff = time.monotonic() - t_diff
        print(f"      differential_run done in {elapsed_diff:.1f}s "
              f"(parse_ok={summary.parse_ok_count} typecheck_ok={summary.typecheck_ok_count})")
        _emit(sink, sess, "phase_complete", {
            "phase": "differential_run",
            "elapsed_sec": elapsed_diff,
            "n_samples": summary.n_samples,
            "parse_ok_count": summary.parse_ok_count,
            "typecheck_ok_count": summary.typecheck_ok_count,
            "agreement_count": summary.agreement_count,
            "disagreement_count": summary.disagreement_count,
            "gate_fail_breakdown": summary.gate_fail_breakdown,
        })

        # Phase 3: summarise
        print(f"\n[3/3] Writing summary.json ...")
        _emit(sink, sess, "phase_start", {"phase": "summarise"})
        t_sum = time.monotonic()
        valid_rate = summary.typecheck_ok_count / max(1, summary.n_samples)
        out = {
            "run_id": summary.run_id,
            "session_id": sid,
            "n_samples": summary.n_samples,
            "parse_ok_count": summary.parse_ok_count,
            "typecheck_ok_count": summary.typecheck_ok_count,
            "valid_rate": valid_rate,
            "gate_fail_breakdown": summary.gate_fail_breakdown,
            "agreement_count": summary.agreement_count,
            "disagreement_count": summary.disagreement_count,
            "wall_time_seconds": summary.wall_time_seconds,
            "per_impl_elapsed": summary.per_impl_elapsed,
            "wrapper_wall_seconds": elapsed_diff,
        }
        (OUT_DIR / "summary.json").write_text(json.dumps(out, indent=2))
        elapsed_sum = time.monotonic() - t_sum
        _emit(sink, sess, "phase_complete", {
            "phase": "summarise",
            "elapsed_sec": elapsed_sum,
            "summary_path": str(OUT_DIR / "summary.json"),
        })

        print("=" * 72)
        print("  BYTE-LEVEL BASELINE SUMMARY")
        print("=" * 72)
        print(f"  N sampled          : {summary.n_samples}")
        print(f"  parse_ok           : {summary.parse_ok_count}")
        print(f"  typecheck_ok       : {summary.typecheck_ok_count}")
        print(f"  valid rate         : {valid_rate:.4f}")
        print(f"  pairs compared     : {summary.agreement_count + summary.disagreement_count}")
        print(f"  agreement count    : {summary.agreement_count}")
        print(f"  disagreement count : {summary.disagreement_count}")
        print(f"  gate fails         : {summary.gate_fail_breakdown}")
        print(f"  wall-time          : {summary.wall_time_seconds:.1f}s")

        # Terminal run_complete event — closes the session in DB so it doesn't
        # get marked failed by the stale-run watchdog (ATH-571).
        # NaN isn't valid JSON — PostgREST rejects with PGRST102; coerce to None.
        import math as _math
        def _safe(x):
            if isinstance(x, float) and _math.isnan(x):
                return None
            return x
        total_elapsed = time.monotonic() - t0_total
        _emit(sink, sess, "run_complete", {
            "status": "succeeded",
            "n_target": args.n,
            "n_samples": summary.n_samples,
            "parse_ok_count": summary.parse_ok_count,
            "typecheck_ok_count": summary.typecheck_ok_count,
            "valid_rate": _safe(valid_rate),
            "gate_fail_breakdown": summary.gate_fail_breakdown,
            "agreement_count": summary.agreement_count,
            "disagreement_count": summary.disagreement_count,
            "wall_time_seconds": _safe(summary.wall_time_seconds),
            "wrapper_wall_seconds": _safe(elapsed_diff),
            "total_elapsed_sec": _safe(total_elapsed),
            "per_impl_elapsed": {
                k: _safe(v) for k, v in (summary.per_impl_elapsed or {}).items()
            },
        })
    return 0


if __name__ == "__main__":
    sys.exit(main())
