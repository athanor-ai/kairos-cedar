"""Exp 3: LM-proposer writes tactic proofs for lean-theorem-proving
student-data benchmarks. Target is the contrastive point to Exp 2 —
LLMs DO have Lean 4 Std + Mathlib-style corpus in pretraining, so
valid_rate > 0 here falsifies a naive "LLMs can't do Lean" read of
Exp 2 and sharpens the §6.3 tool-grounding claim.

Shape (different from Exp 2 generator_synthesize loop):

* Pick a student_data/*.lean with a single `theorem … := by sorry`
  warm-up (e.g. MaxSubarray / Sqrt3Irrational step 1).
* Prompt LLM for a tactic proof that replaces the sorry.
* Assemble complete module + run kairos.lean.verify_proof in
  lake-project mode against the lean-theorem-proving Lake project
  at ~/agents/platform/lean-theorem-proving.
* Iterate: on failure, prompt next iteration with the lean diagnostic.
* Trace per iteration via kairos.session + manual TraceEvent emit
  (run_subtype="theorem_proving" — ATH-565).

Usage:

    EXP3_MODEL=anthropic/claude-sonnet-4-6 python run_lm_lean_tp.py

Env vars:
  EXP3_MODEL          — provider/model slug (default sonnet-4-6)
  EXP3_TARGET_LEMMA   — path to .lean file (default Sqrt3Irrational step 1)
  EXP3_MAX_ITERS      — max iterations (default 3)
  EXP3_LEAN_TP_PATH   — workspace path (default ~/agents/platform/lean-theorem-proving)
  KAIROS_TRACE_SINK   — 'supabase' (default) or 'noop'
  ATHANOR_SYNC_TOKEN  — required for supabase sink (ATH-550)
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

SDK_SRC_CANDIDATES = [
    "/home/azureuser/agents/platform/athanor-sdk/src",
    "/home/azureuser/agents/qa/athanor-sdk/src",
]
for c in SDK_SRC_CANDIDATES:
    if Path(c, "kairos", "lean.py").exists():
        sys.path.insert(0, c)
        break

from kairos.lean import verify_proof  # noqa: E402
from kairos.model_client import get_client  # noqa: E402
from kairos.prove import session as kairos_session  # noqa: E402
from kairos.trace import NoopTraceSink, SupabaseTraceSink, TraceEvent  # noqa: E402


DEFAULT_LEAN_TP = Path.home() / "agents" / "platform" / "lean-theorem-proving"

# First easy-tier step from Sqrt3Irrational — "squares mod 3 are 0 or 1".
# Pre-provable with `decide` or a small omega/match, good warm-up.
DEFAULT_LEMMA_SRC = """\
-- Step 1 (easy): squares mod 3 are 0 or 1
theorem sq_mod3 (n : Nat) : n * n % 3 = 0 ∨ n * n % 3 = 1 := by
  sorry
"""

DEFAULT_LEMMA_NAME = "sq_mod3"


# ─────────────────────────────────────────────────────────────────────
# Prompt assembly
# ─────────────────────────────────────────────────────────────────────


SYSTEM_PROMPT = """You are a Lean 4 theorem prover. The target is a Lean 4
project WITHOUT Mathlib: only the core Lean 4 Std library + Classical
logic is in scope. Tactics like `linarith`, `ring`, `tauto`, `aesop`,
`omega`'s Mathlib variants are NOT available. Use basic tactics:
`rfl`, `decide`, `omega` (core), `simp`, `exact`, `constructor`,
`rcases`, `induction`, `Nat.rec`, `Classical.em`, `by_contra`.

For each prompt you receive a theorem statement with `:= by sorry`.
Produce the proof tactic block that replaces `sorry`. Your response
MUST contain exactly one `PROOF:` block with the tactic code, e.g.:

PROOF:
```lean
decide
```

Do not include the theorem header, imports, or any prose outside the
PROOF: block. Do not use Mathlib.
"""


def build_prompt(theorem_src: str, previous_errors: list[str]) -> str:
    """Assemble the user message for one iteration."""
    parts = [
        "Theorem statement (replace `sorry` with your tactic proof):",
        "",
        "```lean",
        theorem_src.rstrip(),
        "```",
    ]
    if previous_errors:
        parts.append("")
        parts.append("Previous attempts failed with the Lean kernel output:")
        for i, err in enumerate(previous_errors[-3:], start=1):
            # Cap per-error body so the prompt stays bounded.
            parts.append(f"")
            parts.append(f"Attempt {i} diagnostic:")
            parts.append("```")
            parts.append(err[:1500])
            parts.append("```")
        parts.append("")
        parts.append(
            "Produce a DIFFERENT proof. Do not repeat the failed approach."
        )
    return "\n".join(parts)


_PROOF_RE = re.compile(
    r"PROOF\s*:\s*\n?(?:```(?:lean)?\n)?(.*?)(?:\n```|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def extract_proof_block(text: str) -> str:
    """Pull the tactic block out of the LLM's response. Strips fences
    if present. Returns empty string when the response has no PROOF:
    block."""
    m = _PROOF_RE.search(text)
    if not m:
        return ""
    return m.group(1).strip()


def assemble_module(theorem_src: str, proof_block: str) -> str:
    """Splice the proof into the theorem's sorry position. Keeps the
    target theorem's original signature + adds the proof body."""
    replaced = theorem_src.replace("by\n  sorry", f"by\n  {proof_block}")
    if "sorry" in replaced:
        # Fallback — plain "sorry" replacement. Some variants use ` := sorry`.
        replaced = theorem_src.replace("sorry", proof_block)
    return replaced


# ─────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────


def main() -> int:
    sink_kind = os.environ.get("KAIROS_TRACE_SINK", "supabase").lower()
    sink = SupabaseTraceSink() if sink_kind == "supabase" else NoopTraceSink()
    print(f"[exp 3 lean-tp] trace sink = {type(sink).__name__}")

    workspace = Path(os.environ.get("EXP3_LEAN_TP_PATH", str(DEFAULT_LEAN_TP)))
    if not (workspace / "lakefile.toml").exists() and not (
        workspace / "lakefile.lean"
    ).exists():
        print(f"[exp 3 lean-tp] ERROR: no lakefile at {workspace}")
        return 2

    # For now use the inline default. EXP3_TARGET_LEMMA env var could
    # point at a student_data/*.lean file for richer lemma targets.
    theorem_src = DEFAULT_LEMMA_SRC
    theorem_name = DEFAULT_LEMMA_NAME
    scratch_module = f"KairosLeanTP.Scratch.{theorem_name}"

    model = os.environ.get("EXP3_MODEL", "anthropic/claude-sonnet-4-6")
    max_iters = int(os.environ.get("EXP3_MAX_ITERS", "3"))
    print(f"[exp 3 lean-tp] model={model} max_iters={max_iters}")
    print(f"[exp 3 lean-tp] workspace={workspace}")
    print(f"[exp 3 lean-tp] target={theorem_name}")

    client = get_client(model)

    previous_errors: list[str] = []
    total_cost = 0.0
    converged = False
    final_proof = ""

    t_start = time.monotonic()
    with kairos_session(
        f"lean-tp-{theorem_name}-{model.split('/')[-1]}",
        trace_sink=sink,
        vertical="auth",
        run_subtype="theorem_proving",  # ATH-565
    ) as sess:
        for iter_idx in range(max_iters):
            prompt = build_prompt(theorem_src, previous_errors)
            t_iter = time.monotonic()
            resp = client.call(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2000,
                temperature=0.2,
                timeout=120,
            )
            elapsed = time.monotonic() - t_iter

            proof_block = extract_proof_block(resp.content or "")
            assembled = assemble_module(theorem_src, proof_block) if proof_block else ""

            cost = (
                (resp.prompt_tokens + resp.completion_tokens) * 0.0
            )  # cost comes from SDK estimate; leave 0 for now
            total_cost += cost

            if not proof_block:
                reason = "LLM response missing PROOF: block"
                result_obj = None
                verified = False
            else:
                # Run verify_proof in lake-project mode.
                result_obj = verify_proof(
                    assembled,
                    lake_project=workspace,
                    module_path=scratch_module,
                    timeout=600,
                )
                verified = result_obj.compiles and not result_obj.has_sorry
                reason = (
                    "proof compiles clean"
                    if verified
                    else "\n".join(result_obj.errors or [])[:2000]
                )

            # Emit per-iteration TraceEvent so /solve-runs + /activity
            # pick up each attempt.
            event = TraceEvent(
                run_id=sess.session_id,
                run_type="sdk_orchestration",
                run_subtype="theorem_proving",
                event_type="lean_tp_iteration",
                sequence=iter_idx,
                payload={
                    "iteration": iter_idx,
                    "model": model,
                    "theorem_name": theorem_name,
                    "verified": verified,
                    "has_sorry": bool(result_obj and result_obj.has_sorry),
                    "compiles": bool(result_obj and result_obj.compiles),
                    "tokens_in": resp.prompt_tokens,
                    "tokens_out": resp.completion_tokens,
                    "elapsed_sec": round(elapsed, 3),
                    "proof_preview": (proof_block[:500] if proof_block else ""),
                    "reason_tail": reason[-1000:],
                },
            )
            try:
                sink.emit(event)
            except Exception as exc:  # noqa: BLE001
                print(f"[exp 3 lean-tp] sink.emit raised: {exc}")

            print(
                f"[exp 3] iter={iter_idx} verified={verified} "
                f"tokens_in={resp.prompt_tokens} tokens_out={resp.completion_tokens} "
                f"elapsed={elapsed:.1f}s"
            )
            if reason and not verified:
                print(f"  reason: {reason[:400]}")

            if verified:
                converged = True
                final_proof = proof_block
                break

            previous_errors.append(reason)

    total_elapsed = time.monotonic() - t_start
    print(f"[exp 3] session_id={sess.session_id}")
    print(f"[exp 3] converged={converged}")
    print(f"[exp 3] iterations={iter_idx + 1}")
    print(f"[exp 3] total_elapsed={total_elapsed:.1f}s")
    if converged:
        print(f"[exp 3] final proof:\n{final_proof}")
    return 0 if converged else 1


if __name__ == "__main__":
    sys.exit(main())
