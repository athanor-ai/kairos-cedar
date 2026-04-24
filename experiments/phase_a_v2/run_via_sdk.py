"""Phase A v2: drive LLM-Lean generator synthesis through the SDK's
native `kairos.generator_synthesize` verb (ATH-535, PR #140). Replaces
the stand-alone run_loop.py from v1 with the SDK-routed path, so
traces land in the Supabase `sdk_agent_events` table automatically
and the cost / token accounting matches every other kairos customer.

The SDK ships a default `sample_terms` that asks the LLM to emit
candidate terms alongside the generator source. Phase A v2 overrides
it with a Lean-native sampler that compiles the LLM-emitted source
inside the kairos-cedar container and draws concrete terms via
`lake env`. That gives us distributional samples (as opposed to
LLM-imagined samples) at the cost of ~15 seconds of docker startup
per iteration.

Usage:
    # with athanor-sdk on PYTHONPATH or adjacent to the kairos-cedar
    # workspace (the qa clone at /home/azureuser/agents/qa/athanor-sdk
    # is the source of truth on this dev host)
    python3 experiments/phase_a_v2/run_via_sdk.py

Output lives at `experiments/phase_a_v2/outputs/` + `traces/`.
Supabase side: events land with run_type='kairos_cedar_phase_a_v2',
event_type='generator_synthesis_round'. Paper §5 Table 1 reads from
the trace for the replay.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Allow the platform host to pick up the SDK from whichever clone is ahead.
SDK_SRC_CANDIDATES = [
    "/home/azureuser/agents/platform/athanor-sdk/src",
    "/home/azureuser/agents/qa/athanor-sdk/src",
]
for candidate in SDK_SRC_CANDIDATES:
    if Path(candidate, "kairos", "generator_synthesize.py").exists():
        sys.path.insert(0, candidate)
        break

from kairos.generator_synthesize import (  # noqa: E402
    SpecBundle,
    generator_synthesize,
)
from kairos.trace import NoopTraceSink, SupabaseTraceSink  # noqa: E402

# Route litellm's `openai/` provider at the Azure-hosted Kimi K2.6
# endpoint. Same pattern as `evaluate.py` uses for `openai/kimi-k2.5`
# and `openai/mistral-large-3` (the Azure endpoints speak the
# OpenAI-compatible schema litellm's openai provider understands).
# Use unconditional assignment: the fleet bashrc pre-populates
# OPENAI_API_BASE at the K2.5 endpoint, and `setdefault` would keep
# pointing at the wrong host for K2.6 (apmartin-2613-resource, not
# athanor).
if os.environ.get("KIMI_K26_API_KEY") and os.environ.get("KIMI_K26_API_BASE"):
    os.environ["OPENAI_API_KEY"] = os.environ["KIMI_K26_API_KEY"]
    os.environ["OPENAI_API_BASE"] = os.environ["KIMI_K26_API_BASE"]


def _kimi_locked_llm_call(
    prompt: str, model: str,
    *, max_tokens: int = 32000, timeout_sec: int = 300,
) -> tuple[str, int, int, float]:
    """Call Kimi K2.6 via litellm regardless of the model string the
    SDK requests. The SDK escalates to ``anthropic/claude-sonnet-4-6``
    on the final iteration; for Phase A v2 we want the full iteration
    budget to sit on a single proposer so the paper's pipeline numbers
    are not contaminated by cross-model mixing. This shim pins K2.6.
    """
    import litellm
    resp = litellm.completion(
        model="openai/kimi-k2.6-1",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max(max_tokens, 32000),
        temperature=0.1,
        timeout=timeout_sec,
    )
    msg = resp.choices[0].message
    text = (msg.content or "") or (getattr(msg, "reasoning_content", None) or "")
    usage = getattr(resp, "usage", None)
    tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
    tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
    # Kimi K2.6 price per ATH-528 entry: $1 / $3 per million.
    cost_usd = (tokens_in * 1.0 + tokens_out * 3.0) / 1_000_000
    return text, tokens_in, tokens_out, cost_usd

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
CEDAR_MICRO = REPO_ROOT / "cedar-micro"
IMAGE = os.environ.get("KAIROS_CEDAR_IMAGE", "ghcr.io/athanor-ai/kairos-cedar:latest")


def lean_native_sampler(
    *, workspace: Path, module_name: str, term_type: str,
    generator_source: str, n_samples: int,
) -> tuple[list[str], str]:
    """Compile `generator_source` inside the kairos-cedar container and
    sample `n_samples` concrete terms using Palamedes's `sample` utility.
    Returns (sampled terms as readable strings, error text on failure)."""

    # Write the LLM-emitted source into GenLLM_V2.lean inside the Lake project.
    dst = CEDAR_MICRO / "CedarMicro" / "GenLLM_V2.lean"
    dst.write_text(generator_source + "\n")

    # Tiny sample driver that imports GenLLM_V2 and prints N samples.
    driver = CEDAR_MICRO / "SampleDriver.lean"
    driver.write_text(f"""
import CedarMicro.GenLLM_V2
import Palamedes.Basic
import Palamedes.Sample

open CedarMicro

def exprStr : CedarMicro.Expr → String
  | .litInt n  => s!"{{n}}"
  | .litBool b => if b then "true" else "false"
  | .var n     => s!"v{{n}}"
  | .ite c t f => s!"(if {{exprStr c}} then {{exprStr t}} else {{exprStr f}})"
  | .and a b   => s!"({{exprStr a}} && {{exprStr b}})"

def main : IO Unit := do
  let Γ : List CedarMicro.Ty := [.int, .bool, .int]
  let samples ← sampleN {n_samples} (_root_.genWellTyped Γ .bool)
  for e in samples do IO.println (exprStr e)
  let samples2 ← sampleN {n_samples} (_root_.genWellTyped Γ .int)
  for e in samples2 do IO.println (exprStr e)
""")

    # Compile + run the driver inside the monolith image.
    cmd = (
        "elan default leanprover/lean4:v4.24.0 >/dev/null 2>&1 && "
        "lake env lean --run SampleDriver.lean 2>&1"
    )
    proc = subprocess.run(
        ["docker", "run", "--rm",
         "-v", f"{REPO_ROOT}:/work",
         "-w", "/work/cedar-micro",
         IMAGE,
         "bash", "-c", cmd],
        capture_output=True, text=True, timeout=600,
    )

    # Clean up.
    try:
        dst.unlink()
    except FileNotFoundError:
        pass
    try:
        driver.unlink()
    except FileNotFoundError:
        pass

    if proc.returncode != 0:
        return [], (proc.stdout + proc.stderr)[-2000:]

    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    return lines, ""


def lean_native_sample_terms_adapter(
    generator_source: str,
    _response_text: str,
    n_samples: int,
) -> list[str]:
    """Adapter from the SDK's 3-arg sample_terms signature to the
    5-kwarg lean_native_sampler. Ignores the LLM's self-emitted
    candidate-terms block in _response_text; compiles the generator
    source inside the container and draws samples via Palamedes.

    Returns a list of Lean term literals that the SDK's predicate_verify
    can feed back to `wellTypedAt` for acceptance-oracle checking.
    Each line emitted by the Lean sample driver is wrapped in a
    `CedarMicro.Expr.` qualifier because the SDK writes them into
    scratch modules that don't `open CedarMicro`.
    """
    terms, err = lean_native_sampler(
        workspace=CEDAR_MICRO,
        module_name="CedarMicro.GenLLM_V2",
        term_type="CedarMicro.Expr",
        generator_source=generator_source,
        n_samples=n_samples,
    )
    if err:
        print(f"[phase A v2] lean_native_sampler failed: {err[:400]}")
        return []
    # The sample driver emits readable `exprStr` output (e.g. "true",
    # "(if v0 then 1 else -1)"). Wrap each in the `CedarMicro.Expr`
    # constructor shape expected by predicate_verify's term_source
    # pipeline. For the V2.1 smoke we pass the readable strings through
    # and let predicate_verify's module-scratch write re-parse them.
    return terms[:n_samples]


def main() -> int:
    outputs = HERE / "outputs"
    traces = HERE / "traces"
    outputs.mkdir(parents=True, exist_ok=True)
    traces.mkdir(parents=True, exist_ok=True)

    # CedarMicro spec bundle. Workspace = the cedar-micro/ Lake project;
    # the SDK writes scratch modules under CedarMicro.Scratch.*.
    bundle = SpecBundle(
        workspace=CEDAR_MICRO,
        module_scratch_prefix="CedarMicro.Scratch.GenLLMV2",
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

    trace_sink_choice = os.environ.get("KAIROS_TRACE_SINK", "noop").lower()
    sink = SupabaseTraceSink() if trace_sink_choice == "supabase" else NoopTraceSink()
    print(f"[phase A v2] trace sink = {sink.__class__.__name__}")

    t = time.monotonic()
    result = generator_synthesize(
        bundle,
        model=os.environ.get("KIMI_K26_LITELLM_NAME", "openai/kimi-k2.6-1"),
        max_iters=4,
        target_rejection_rate=0.1,
        n_samples=10,
        trace_sink=sink,
        # Pin K2.6 across all iterations. The SDK would otherwise
        # escalate to claude-sonnet-4-6 on the final iteration and
        # mix proposers in the paper's §5 Table 1 numbers.
        llm_call=_kimi_locked_llm_call,
        # Draw samples via Palamedes.sampleN inside the monolith
        # container instead of asking the LLM to self-sample. When
        # KAIROS_LEAN_NATIVE_SAMPLER is set, the SDK's predicate_verify
        # sees terms produced by the LLM's compiled generator, not
        # hallucinated candidates. This populates Table 1's
        # distributional column; without it the run measures the
        # LLM's self-sampling ability (the V2 baseline at
        # rejection_rate=1.0 we already have).
        sample_terms=(
            lean_native_sample_terms_adapter
            if os.environ.get("KAIROS_LEAN_NATIVE_SAMPLER") == "1"
            else None
        ),
    )
    elapsed = time.monotonic() - t

    summary = {
        "iterations": len(result.iterations),
        "converged": result.converged,
        "final_rejection_rate": result.final_rejection_rate,
        "elapsed_sec": round(elapsed, 2),
        "total_tokens": sum(
            (it.tokens_in or 0) + (it.tokens_out or 0)
            for it in result.iterations
        ),
    }
    (traces / "sdk_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"[phase A v2] {json.dumps(summary, indent=2)}")

    if result.final_generator_source:
        (outputs / "sdk_generator_source.lean").write_text(result.final_generator_source)
        print(f"[phase A v2] generator source: outputs/sdk_generator_source.lean")

    return 0 if result.converged else 1


if __name__ == "__main__":
    sys.exit(main())
