"""Backfill archived Phase A V1 + V2 runs into Supabase (Aidan directive
2026-04-24 02:45Z: "backfill any data you must to the database right now").

Writes:
  - solve_runs parent row per archived run (with backfill-note in workdir_path)
  - sdk_agent_events child rows per iteration

Timestamps: started_at = the archived run's actual UTC wall-clock
(recovered from the RESULTS.md / sdk_summary.json / log filename
timestamps where possible). finished_at = started_at + elapsed_sec.

Attribution: each event's payload carries backfill=True and source_file
so the provenance is auditable. Parent row's workdir_path likewise.

Run once; idempotent on the synthetic run_ids (UPSERT by id).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request as urlreq
import urllib.error as urlerr
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

SB_URL = os.environ["NEXT_PUBLIC_SUPABASE_URL"]
SB_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent


def deterministic_uuid(seed: str) -> str:
    """Stable UUID from a seed string so re-running the backfill
    upserts the same row rather than creating duplicates."""
    h = hashlib.sha256(seed.encode()).digest()[:16]
    return str(UUID(bytes=h))


def sb_upsert(table: str, row: dict) -> None:
    url = f"{SB_URL}/rest/v1/{table}"
    req = urlreq.Request(
        url,
        method="POST",
        data=json.dumps(row).encode(),
        headers={
            "apikey": SB_KEY,
            "Authorization": f"Bearer {SB_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
    )
    try:
        urlreq.urlopen(req, timeout=30)
    except urlerr.HTTPError as e:
        body = e.read().decode()
        print(f"  FAIL {table}: HTTP {e.code} — {body[:200]}", file=sys.stderr)
        raise


def backfill_v1() -> None:
    """Phase A V1: 2 iters, Kimi K2.6-1, ~$0.12, ~100s wall,
    RESULTS.md documents the outcome."""
    run_id = deterministic_uuid("kairos-cedar.phase-a-v1.2026-04-23")
    # V1 ran 2026-04-23 evening; commit 82a2969 pinned the fix. Use
    # 21:00Z as the nominal start time (RESULTS.md cites the outcome
    # but no exact timestamp).
    start = datetime(2026, 4, 23, 21, 0, 0, tzinfo=timezone.utc)
    elapsed_sec = 100.94  # iter_1 + iter_2 call_elapsed_sec
    finish = datetime.fromtimestamp(
        start.timestamp() + elapsed_sec, tz=timezone.utc,
    )

    parent_id = deterministic_uuid(f"solve_runs.{run_id}")
    print(f"[v1] parent run_id={run_id} cost=$0.1225 iters=2 converged=True")
    sb_upsert("solve_runs", {
        "id": parent_id,
        "vertical": "auth",
        "target": run_id,
        "pipeline_version": "kairos-cedar/phase-a-v1",
        "builder_model": "openai/kimi-k2.6-1",
        "status": "succeeded",
        "token_cost_usd": 0.1225,
        "wall_time_seconds": elapsed_sec,
        "refutation_loops": 1,  # 1 compile retry on iter 1
        "workdir_path": (
            "backfill:experiments/phase_a_v1/traces/loop_summary.json"
        ),
        "source_pipeline": "auth_cedar",
        "started_at": start.isoformat(),
        "finished_at": finish.isoformat(),
        "dry_run": False,
    })

    iters = [
        {
            "iteration": 1, "reasoning_tokens": 15415,
            "completion_tokens": 16051, "prompt_tokens": 1049,
            "call_elapsed_sec": 77.08, "compile_ok": False,
            "failure_note": "Unknown constant 'Gen.pure'",
        },
        {
            "iteration": 2, "reasoning_tokens": 4461,
            "completion_tokens": 5088, "prompt_tokens": 2318,
            "call_elapsed_sec": 23.86, "compile_ok": True,
        },
    ]
    for it in iters:
        event_id = deterministic_uuid(
            f"event.{run_id}.iter{it['iteration']}"
        )
        sb_upsert("sdk_agent_events", {
            "id": event_id,
            "run_id": run_id,
            "session_id": run_id,
            "run_type": "sdk_orchestration",
            "run_subtype": "spec_pipeline",
            "event_type": "generator_synthesis_round",
            "sequence": it["iteration"] - 1,
            "payload": {
                **it,
                "model": "openai/kimi-k2.6-1",
                "backfill": True,
                "source_file": (
                    "experiments/phase_a_v1/traces/loop_summary.json"
                ),
                "notes": (
                    "Retrospective backfill per Aidan 2026-04-24 02:45Z "
                    "directive. Original run was 2026-04-23 evening "
                    "pre-ATH-544 (env-var fallback), wrote to local "
                    "trace files only."
                ),
            },
        })


def backfill_v2() -> None:
    """Phase A V2: 4 iters, Kimi K2.6-1 via openai/ prefix, 100k
    tokens, ~$0.11, elapsed 880s, rejection_rate 1.0. sdk_summary.json
    documents totals; no per-iter breakdown in the archived summary."""
    run_id = deterministic_uuid("kairos-cedar.phase-a-v2.2026-04-24")
    # First V2 run started 2026-04-24 00:03:29Z (log filename).
    start = datetime(2026, 4, 24, 0, 3, 29, tzinfo=timezone.utc)
    elapsed_sec = 880.74
    finish = datetime.fromtimestamp(
        start.timestamp() + elapsed_sec, tz=timezone.utc,
    )

    parent_id = deterministic_uuid(f"solve_runs.{run_id}")
    print(f"[v2] parent run_id={run_id} cost~$0.11 iters=4 rejection=1.0")
    sb_upsert("solve_runs", {
        "id": parent_id,
        "vertical": "auth",
        "target": run_id,
        "pipeline_version": "kairos-cedar/phase-a-v2",
        "builder_model": "openai/kimi-k2.6-1",
        "status": "succeeded",
        "token_cost_usd": 0.1068,  # 100059 tokens at $1/$3 per M, rough mix
        "wall_time_seconds": elapsed_sec,
        "refutation_loops": 4,
        "workdir_path": (
            "backfill:experiments/phase_a_v2/outputs/"
            "sdk_run_20260424_000329.log"
        ),
        "source_pipeline": "auth_cedar",
        "started_at": start.isoformat(),
        "finished_at": finish.isoformat(),
        "dry_run": False,
    })

    # Archived summary does not carry per-iter tokens. Emit a single
    # aggregate event capturing what the summary.json has.
    event_id = deterministic_uuid(f"event.{run_id}.aggregate")
    sb_upsert("sdk_agent_events", {
        "id": event_id,
        "run_id": run_id,
        "session_id": run_id,
        "run_type": "sdk_orchestration",
        "run_subtype": "spec_pipeline",
        "event_type": "generator_synthesis_run_aggregate",
        "sequence": 0,
        "payload": {
            "iterations": 4,
            "converged": False,
            "final_rejection_rate": 1.0,
            "elapsed_sec": 880.74,
            "total_tokens": 100059,
            "model": "openai/kimi-k2.6-1",
            "backfill": True,
            "source_file": (
                "experiments/phase_a_v2/traces/sdk_summary.json"
            ),
            "notes": (
                "Aggregate event. Original V2 summary.json does not "
                "carry per-iter breakdowns. Retrospective backfill "
                "per Aidan 2026-04-24 02:45Z directive. Original "
                "run used KAIROS_TRACE_SINK=noop during the "
                "Kimi-cooldown policy-error window."
            ),
        },
    })


def main() -> int:
    print("backfilling Phase A V1...")
    backfill_v1()
    print("backfilling Phase A V2...")
    backfill_v2()
    print("done. Query: SELECT id, target, token_cost_usd, started_at "
          "FROM solve_runs WHERE pipeline_version LIKE 'kairos-cedar/%' "
          "ORDER BY started_at;")
    return 0


if __name__ == "__main__":
    sys.exit(main())
