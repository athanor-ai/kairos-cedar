# Phase A V1 results: LLM-synthesised Cedar-micro generator with Lean verification loop

**Question.** Can a reasoning LLM write a correct type-directed property-based test generator for a Cedar-shape language, with a proof-assistant acting as the oracle for generator correctness?

**Answer (this run).** Yes, in 2 iterations, ~$0.12 of model cost, ~100 seconds wall-clock.

## Setup

- Target language: `CedarMicro` (`Ty = bool | int`; `Expr = litInt | litBool | var | ite | and`).
- Specification provided to the model: the Lean 4 `inductive` definitions, the functional typechecker `getType`, and the target `genWellTyped : List Ty -> Ty -> Gen Expr` signature.
- Verification oracle: `wellTypedAt : List Ty -> Ty -> Expr -> Bool`, which runs `getType` and compares against the requested target type.
- Iteration controller: on compile failure, the prior source and the tail of the Lean error log are sent back to the model as the next prompt turn.
- Model: Kimi 2.6-1 (`kimi-k2.6-1`) via the Azure-hosted OpenAI-compatible endpoint.
- Infrastructure: public `ghcr.io/athanor-ai/kairos-cedar:latest` image; all compilation and sampling happen inside the container.

## Per-iteration trace

| Iter | Wall time | Reasoning tokens | Completion tokens | Result |
| --- | --- | --- | --- | --- |
| 1 | 77.1 s | 15,415 | 636 | compile fail: `Unknown constant 'Gen.pure'` (used `Gen.pure` where the namespace is just `pure`) |
| 2 | 23.9 s | 4,461 | 627 | **compile pass** |

Total: 19,876 reasoning tokens, 1,263 completion tokens, 24,506 tokens overall, approximately **$0.12** at a placeholder $5 / 1M rate.

## Sampled output

After iter 2 compiled, we sampled 20 expressions at each of `.bool` and `.int` under `Γ = [.int, .bool, .int]` and evaluated each against `wellTypedAt`.

- Bool samples: 20/20 verified well-typed.
- Int samples: 20/20 verified well-typed.
- Overall rejection rate: 0%.

A few sampled bool expressions:

```
v1
(if (v1 && true) then true else (((if v1 then v1 else true) && (true && false)) && false))
(true && (if (if (v1 && v1) then (false && false) else (if true then true else v1)) then v1 else false))
```

A few sampled int expressions:

```
v2
(if v1 then -1 else (if ((if v1 then v1 else v1) && false) then (if (if false then v1 else true) then (if v1 then v0 else v2) else 0) else (if (v1 && false) then (if v1 then 0 else 1) else (if true then -1 else 1))))
(if (if ((v1 && v1) && (true && false)) then v1 else v1) then v2 else (if (v1 && v1) then (if false then v0 else (if v1 then 1 else 1)) else (if v1 then (if false then 1 else 0) else v2)))
```

Non-trivial nesting in both types. `var` indices only reference type-compatible positions in `Γ` (e.g. `v0` and `v2` for `int` because `Γ = [int, bool, int]`).

## Reproduction

```
git clone --recurse-submodules https://github.com/athanor-ai/kairos-cedar.git
cd kairos-cedar
docker pull ghcr.io/athanor-ai/kairos-cedar:latest
export KIMI_K26_API_BASE=...
export KIMI_K26_API_KEY=...
python3 experiments/phase_a_v1/run_loop.py
docker run --rm -v "$PWD":/work -w /work/cedar-micro \
    ghcr.io/athanor-ai/kairos-cedar:latest \
    bash -c 'elan default leanprover/lean4:v4.24.0 && \
             lake build cedar-micro-sample-llm && \
             .lake/build/bin/cedar-micro-sample-llm 20'
```

The final generator source the model produced lives at `experiments/phase_a_v1/outputs/loop_iter_2.lean` (and is copied into `cedar-micro/CedarMicro/GenLLM.lean` for the sample runner).

## Observations

1. The verification loop is load-bearing. Iter 1 produced a structurally reasonable generator that would have typechecked at the Lean level only if the helper functions used `pure` (the polymorphic monadic unit) rather than `Gen.pure`. A generator accepted by the programmer's eye but rejected by the Lean compiler is exactly the regime where an LLM-only workflow fails silently.
2. Reasoning tokens dominate token usage (roughly 90%), as expected for a reasoning model. The `completion_tokens` figure captures the visible Lean source; the reasoning trace explains the model's internal debugging and is not written out.
3. The second iteration converged faster than the first (23.9 s vs 77.1 s) because most of the reasoning from iter 1 transfers: once the model had the generator structure right, the fix was a local rename.
4. Zero rejection rate on 40 samples is encouraging but a stronger test requires scaling to the full Cedar `Expr` (12 constructors, extensions) where the generator has many more ways to produce ill-typed output. That is Phase B.

## What this does not yet show

- Robustness across model temperatures or alternative prompts.
- Comparison against a hand-authored baseline on identical inputs (planned as T3 in Phase A).
- Bug-finding against a real Cedar implementation (Phase B).
- Ablation of the verification loop vs one-shot generation (part of Phase C).

## Next step

Expand this experimental pattern to an ablation grid: Kimi 2.6 / Sonnet / Opus as generator-writer; with-feedback vs without; CedarMicro / partial Cedar subsets. Numbers against identical budgets. Then scale to full Cedar for bug-finding (Phase B).
