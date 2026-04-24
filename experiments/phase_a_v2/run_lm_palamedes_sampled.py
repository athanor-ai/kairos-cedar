"""Exp 2 proper: LM-proposer writes the generator source; Palamedes
samples from it at runtime; acceptance oracle verifies each sample.

Pre-ATH-546 the SDK's default sample_terms asked the LLM to
self-sample. Sonnet/Kimi both failed at 100% rejection across
CedarMicro + cedar-full. Post-ATH-546 (+ ATH-557 for multi-project
Lake mount) we can wire sample_terms= to kairos.lean.sample_generator,
which drives the LM's compiled Gen source through Palamedes.sampleN
inside the workbench container. That's the pipeline variant the
paper's Table 1 col 2 should measure.

Target: CedarMicro, Sonnet proposer, 3 iters × 5 per-iter samples.
All tracing auto-on via ATH-550 (ATHANOR_SYNC_TOKEN-gated + session
auto-wrap).
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
for c in SDK_SRC_CANDIDATES:
    if Path(c, "kairos", "generator_synthesize.py").exists():
        sys.path.insert(0, c)
        break

from kairos.generator_synthesize import (  # noqa: E402
    SpecBundle, generator_synthesize,
)
from kairos.prove import session as kairos_session  # noqa: E402
from kairos.trace import NoopTraceSink, SupabaseTraceSink  # noqa: E402
from kairos.lean import sample_generator  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
CEDAR_MICRO = REPO_ROOT / "cedar-micro"


def palamedes_sample_terms_adapter(
    generator_source: str, _response_text: str, n_samples: int,
) -> list[str]:
    """Drop-in for the SDK's sample_terms kwarg. Writes the LLM's
    generator source into cedar-micro/CedarMicro/GenLLM_V2.lean,
    then calls kairos.lean.sample_generator to draw n_samples
    terms via Palamedes.sampleN inside the workbench container.
    Returns the rendered term strings.

    Rollback: removes the scratch module on exit.
    """
    scratch = CEDAR_MICRO / "CedarMicro" / "GenLLM_V2.lean"
    scratch.write_text(generator_source + "\n")
    try:
        r = sample_generator(
            workspace=str(CEDAR_MICRO),
            workspace_root=str(REPO_ROOT),
            module="CedarMicro.GenLLM_V2",
            term_type="CedarMicro.Expr",
            generator_expr=(
                f"sampleN {n_samples} "
                "(CedarMicro.genWellTyped [.int, .bool, .int] .bool)"
            ),
            n=n_samples,
            render_expr="(fun e => reprStr e)",
            extra_imports=["Palamedes.Sample"],
            docker_image="ghcr.io/athanor-ai/kairos-cedar:latest",
            timeout_sec=300,
        )
        if r.error:
            print(f"[palamedes sampler] error: {r.error}")
            if r.stdout_tail:
                print(r.stdout_tail[-600:])
            return []
        return r.terms
    finally:
        try:
            scratch.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    sink = (SupabaseTraceSink()
            if os.environ.get("KAIROS_TRACE_SINK", "supabase").lower()
               == "supabase"
            else NoopTraceSink())
    print(f"[exp 2 LM+palamedes] trace sink = {type(sink).__name__}")

    bundle = SpecBundle(
        workspace=CEDAR_MICRO,
        module_scratch_prefix="CedarMicro.Scratch.LMPalamedes",
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
        "cedar-micro-phase-a-lm-palamedes-sampled",
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
            sample_terms=palamedes_sample_terms_adapter,
        )
    elapsed = time.monotonic() - t

    print(f"[exp 2] session_id={sess.session_id}")
    print(f"[exp 2] iterations={len(result.iterations)}")
    print(f"[exp 2] converged={result.converged}")
    print(f"[exp 2] final_rejection_rate={result.final_rejection_rate}")
    print(f"[exp 2] elapsed_sec={elapsed:.1f}")
    cost = sum(it.cost_usd or 0.0 for it in result.iterations)
    print(f"[exp 2] total_cost_usd={cost:.4f}")
    return 0 if result.converged else 1


if __name__ == "__main__":
    sys.exit(main())
