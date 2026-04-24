"""Sonnet-proposer Phase A rerun with Supabase tracing + kairos.session
wrapper so the parent solve_runs row + child events + aggregated cost
all land in the DB.

Run ID tracked via kairos.session; not hard-coded. Dashboard query:
  SELECT * FROM solve_runs WHERE target = <session_id>
  SELECT * FROM sdk_agent_events WHERE run_id = <session_id>

Aidan 02:31Z directive: future runs in Supabase. This is the first one
after ATH-544 + 545 + 548 all merged.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

SDK_SRC_CANDIDATES = [
    "/home/azureuser/agents/platform/athanor-sdk/src",
    "/home/azureuser/agents/qa/athanor-sdk/src",
]
for candidate in SDK_SRC_CANDIDATES:
    if Path(candidate, "kairos", "generator_synthesize.py").exists():
        sys.path.insert(0, candidate)
        break

from kairos.generator_synthesize import (  # noqa: E402
    SpecBundle, generator_synthesize,
)
from kairos.trace import NoopTraceSink, SupabaseTraceSink  # noqa: E402
from kairos.prove import session as kairos_session  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
CEDAR_MICRO = REPO_ROOT / "cedar-micro"


def main() -> int:
    sink_choice = os.environ.get("KAIROS_TRACE_SINK", "supabase").lower()
    sink = SupabaseTraceSink() if sink_choice == "supabase" else NoopTraceSink()
    print(f"[sonnet traced] trace sink = {sink.__class__.__name__}")

    bundle = SpecBundle(
        workspace=CEDAR_MICRO,
        module_scratch_prefix="CedarMicro.Scratch.SonnetTraced",
        predicate_name="CedarMicro.wellTypedAt",
        predicate_imports=[
            "import CedarMicro.Ty",
            "import CedarMicro.Expr",
            "import CedarMicro.WellTyped",
            "import Palamedes.Gen",
            "open Gen",
        ],
        term_type="CedarMicro.Expr",
        example_term="Expr.litBool true",
    )

    t = time.monotonic()
    with kairos_session(
        "cedar-full-phase-a-sonnet",
        trace_sink=sink,
        vertical="auth",
        run_subtype="generator_synthesis",
    ) as sess:
        result = generator_synthesize(
            bundle,
            model="anthropic/claude-sonnet-4-6",
            max_iters=3,
            target_rejection_rate=0.1,
            n_samples=5,
            trace_sink=sink,
            run_id=sess.session_id,
        )
    elapsed = time.monotonic() - t

    print(f"[sonnet traced] session_id={sess.session_id}")
    print(f"[sonnet traced] iterations={len(result.iterations)}")
    print(f"[sonnet traced] converged={result.converged}")
    print(f"[sonnet traced] final_rejection_rate={result.final_rejection_rate}")
    print(f"[sonnet traced] elapsed_sec={elapsed:.1f}")
    total_cost = sum(it.cost_usd or 0.0 for it in result.iterations)
    print(f"[sonnet traced] total_cost_usd={total_cost:.4f}")
    return 0 if result.converged else 1


if __name__ == "__main__":
    sys.exit(main())
