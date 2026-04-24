# Exp 3 — LLM-proposer for lean-theorem-proving warm-ups

Contrastive experiment to Exp 2 (LM+Palamedes at 0.00 valid rate).
Targets the `lean-theorem-proving/student_data/*.lean` corpus, which
LLMs have substantial pretraining exposure to (Mathlib-style Lean 4
tactic proofs are in public code). Expected result: valid_rate > 0
on warm-ups like `sq_mod3` / `MaxSubarray` / `Nat.add_comm`, which
falsifies a naive "LLMs can't do Lean" read of Exp 2 and strengthens
§6.3's tool-grounding claim (the Palamedes failure was specifically
about unfamiliar API surface, not Lean tactic synthesis generally).

## Shape

Different from Exp 2's `generator_synthesize` loop. Theorem-proving is
"fill the sorry", not "generate candidate terms":

1. Read a `theorem X := by sorry` statement.
2. Prompt LLM for the tactic block.
3. Splice LLM output into a scratch module under the
   lean-theorem-proving Lake project.
4. Run `kairos.lean.verify_proof(..., lake_project=..., module_path=...)`.
5. On failure, feed Lean kernel diagnostic back into next prompt.
6. Iterate until converged or `max_iters` exhausted.

## Run

```bash
# First Sonnet sweep on sq_mod3 (default warm-up).
python experiments/lean_tp_v1/run_lm_lean_tp.py

# Fan out after sonnet lands:
EXP3_MODEL=openai/kimi-k2.6-1 python experiments/lean_tp_v1/run_lm_lean_tp.py
EXP3_MODEL=anthropic/claude-opus-4-6 python experiments/lean_tp_v1/run_lm_lean_tp.py

# Custom lemma target:
EXP3_TARGET_LEMMA=~/agents/platform/lean-theorem-proving/student_data/MaxSubarray.lean \
  python experiments/lean_tp_v1/run_lm_lean_tp.py
```

## Env vars

| var | default | purpose |
| --- | --- | --- |
| `EXP3_MODEL` | `anthropic/claude-sonnet-4-6` | provider/model slug |
| `EXP3_TARGET_LEMMA` | (inline `sq_mod3`) | path to `.lean` with sorry |
| `EXP3_MAX_ITERS` | `3` | max retry loop iterations |
| `EXP3_LEAN_TP_PATH` | `~/agents/platform/lean-theorem-proving` | workspace |
| `KAIROS_TRACE_SINK` | `supabase` | `supabase` or `noop` |
| `ATHANOR_SYNC_TOKEN` | — | required when sink=supabase (ATH-550) |

## Trace shape

Every iteration emits a `TraceEvent`:

- `run_type="sdk_orchestration"`
- `run_subtype="theorem_proving"` (ATH-565 schema widening)
- `event_type="lean_tp_iteration"`
- `payload`: iteration index, model, theorem_name, verified, has_sorry,
  compiles, tokens in/out, elapsed_sec, proof preview (500 chars),
  Lean diagnostic tail (1000 chars).

Events land live in `sdk_agent_events` when `ATHANOR_SYNC_TOKEN` is
set; the parent `solve_runs` row (opened by `kairos.session`) surfaces
in `/solve-runs` with `run_subtypes: ['theorem_proving']` per the
post-ATH-565 dashboard visibility (PR #249).

## Fleet-sweep wrapper

Pattern-match Exp 2's `run_fleet_sweep.sh`:

```bash
for m in anthropic/claude-sonnet-4-6 openai/kimi-k2.6-1 anthropic/claude-opus-4-6; do
  EXP3_MODEL="$m" python run_lm_lean_tp.py 2>&1 \
    | tee "fleet_sweep_${m//\//-}.log"
done
```

## Paper delta

If `valid_rate > 0` across any proposer × lemma, add a contrastive
column to `Table 1` (or a new `Table 4`) in kairos-cedar-paper:

| generator | valid rate | mean depth | cost |
| --- | --- | --- | --- |
| Hand-authored (CedarMicro) | 1.00 | 0.50 | 261 μs/draw |
| LM + Palamedes (Cedar) | 0.00 | n/a | $0.025–0.081/run |
| **LM + Lean-TP (warm-ups)** | **TBD** | **TBD** | **TBD** |

The contrastive row puts the §6.3 tool-grounding claim on firmer
footing — same proposers, same SDK loop, different target corpus →
different valid rate. Strengthens "LLMs can't write to an API surface
they haven't been retrieval-grounded on" by showing the flip side.

## Owner

qa authored the driver; platform drives runs + paper integration per
Aidan 2026-04-24 05:13Z lane split.
