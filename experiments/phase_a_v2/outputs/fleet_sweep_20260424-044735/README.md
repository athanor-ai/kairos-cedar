# Phase-A v2 fleet sweep, 2026-04-24 04:47Z

LM-proposer + Palamedes-runtime-sampling experiment ("Exp 2") on
CedarMicro, three frontier-class proposers under the same workbench
proposer loop, with `sample_terms` wrapping the workbench's
runtime-sampling driver. Produces the paper §6.3 "Failure Modes of
the LM-Proposer Variant" data.

## Runs

| File                            | Model                      | Iters | Sampled | Cost (USD) | Wall (s) |
|---------------------------------|----------------------------|-------|---------|------------|----------|
| anthropic-claude-sonnet-4-6.log  | Anthropic Claude Sonnet 4.6 | 3     | 0       | 0.025      | 74       |
| openai-kimi-k2.6-1.log           | Moonshot Kimi K2.6          | 3     | 0       | 0.008      | 337      |
| anthropic-claude-opus-4-6-retry.log | Anthropic Claude Opus 4.6 (1M) | 3 | 0   | 0.081      | 81       |

(`anthropic-claude-opus-4-7.log` left out: model deployment 4-7 is
not provisioned on the Azure endpoint; the 4-6 retry is the
in-distribution comparison.)

## Failure mode (cross-proposer)

Each proposer's LLM-emitted Lean source fails `lake env lean --run`
with `Unknown constant Gen.<X>` errors. The proposer hallucinates
QuickCheck-shaped combinator names that do not exist in
`Palamedes.Gen`. Verbatim tokens observed across the 9 iterations
total: `Gen.map`, `Gen.oneOf`, `Gen.chooseNat`, `Gen.bool`,
`Gen.range`, `choose`, `oneOf`, `sized`, `chooseNat`, plus
`type mismatch on @Gen.choose ℕ`. Two further iterations failed with
multi-line ambiguous-resolution errors (`_root_.Ty` vs
`CedarMicro.Ty` and similar for `genWellTyped`).

Reading: tool-grounding observation, not capability claim. Same
class as the specialised-prover prompt-inversion mechanism reported
in the Formal-AVS dataset paper.

## Reproducing

```bash
# from the repo root
docker pull ghcr.io/athanor-ai/kairos-cedar:latest
export $(grep -E '^(ANTHROPIC|SUPABASE|KIMI_K26)' /path/to/your/keys.env)
bash experiments/phase_a_v2/run_fleet_sweep.sh
```

Outputs land in a fresh `outputs/fleet_sweep_<ts>/` directory with
one `.log` per model. Each log's `[exp 2] iter=<n>` blocks include
the per-iteration `sample_terms_stdout_tail` field which carries
the verbatim Lean compiler diagnostic for each iteration.
