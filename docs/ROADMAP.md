# Roadmap

Phased plan from infrastructure (V0, shipped) through full differential coverage (V3).

## V0: infrastructure

- Containerised toolchain (`containers/Containerfile`) publishing a single image to `ghcr.io/athanor-ai/kairos-cedar`.
- Upstream submodules pinned: [cedar-spec](https://github.com/cedar-policy/cedar-spec), [palamedes-lean](https://github.com/hgoldstein95/palamedes-lean), [cedar-go](https://github.com/cedar-policy/cedar-go), [cedar-integration-tests](https://github.com/cedar-policy/cedar-integration-tests).
- Lean bridge (`cedar-spec-bridge/`): `isWellTyped env e := ∃ te c, Cedar.Validation.typeOf e [] env = .ok (te, c)` compiles against upstream `cedar-spec`.
- Preflight script, thin dev wrapper `scripts/dc`, unit + hygiene + integration tests, CI.
- Baseline observation: the shipped integration-tests corpus yields zero Rust/Go disagreements at `cedar-go v1.6.0`. The Rust reference and Go reimplementation agree on the published oracle.

## V1: Palamedes synthesis on a flat Cedar-shape subset

Prove the synthesis technique of [1] applies to a Cedar-shape type system before scaling to the full cedar-spec grammar.

- Minimum subset: `Ty = bool | int`, `Expr = litInt Int | litBool Bool | var Nat | ite | and`. Approximately 150 additional lines of Lean beyond the scaffolding port.
- Port the [`palamedes-lean`](https://github.com/hgoldstein95/palamedes-lean) `Data/STLC/*.lean` pattern to the subset: companion functor, recursion schemes, fold coercions, `Gen.arb_τ`, `Gen.case_τ`, `CorrectGen` variants, totality lemmas registered with `@[simp, aesop safe (rule_sets := [totality])]`, and recursor-form `as_or` / `deforest_eq` rewrites. `Ty` portion is done; `Expr` is the open work item.
- Invoke `generator_search (fun e => isWellTyped Γ e)` and verify Aesop closes the goal.
- Sample 10^4 expressions and verify they all type-check under `Cedar.Validation.typeOf` (should hold by construction if the derivation is sound).

## V2: Full `Cedar.Spec.Expr`

- Upgrade [`palamedes-lean`](https://github.com/hgoldstein95/palamedes-lean) to Lean 4.29.1 and the Mathlib revision compatible with `cedar-spec`'s pin. This removes the two-toolchain workaround and lets the Palamedes tactic operate directly on types imported from `cedar-spec`.
- Port the full 12-constructor `Cedar.Spec.Expr` into the companion-functor form the Palamedes scaffolding expects. Extension-typed operators (`call`, datetime, IP) are deferred to the end because they introduce richer arity patterns.
- Add `isWellFormedSchema` and `isValidRequest` bridges mirroring `isWellTyped`. The generator then produces end-to-end `(policy, schema, entity-store, request)` tuples.
- Execute the generated corpus against [cedar-policy/cedar](https://github.com/cedar-policy/cedar) and [cedar-policy/cedar-go](https://github.com/cedar-policy/cedar-go). The experimental question: does fresh, type-directed input exercise shapes the existing integration-tests corpus does not, and does that expose divergences?

## V3: Evaluation and symbolic compilation

Extend the generator from type-checking to the two other semantic tiers exercised by Cedar implementations:

- Evaluation: generate entity stores and requests so that `cedar-policy::authorize` returns a prescribed decision, and compare against `cedar-go`'s decision on the same fixture.
- Symbolic compilation: generate policies compatible with `Cedar.SymCC.Compiler` and test the SMT encoding against the concrete evaluator's verdict on matched requests. Uses Dafny + Z3 for an independent SMT oracle.

## Verus track (optional, parallel)

- Level 1: annotate the Rust differential-test harness (the code that runs both implementations and compares decisions) with [Verus](https://github.com/verus-lang/verus) `requires` and `ensures` preconditions. Proves harness correctness.
- Level 2: annotate a subset of `cedar-policy`'s evaluator (boolean, integer primitives, no entity lookups) and prove soundness against an algebraic specification. Compare the Verus-derived verdicts against the Lean-derived verdicts on identical fixtures. Divergences indicate a defect in at least one of the two formal models.

## Out of scope

- Long-running fuzz orchestration. Integrate with `cargo fuzz` or a managed fuzzer if continuous fuzzing is required.
- Closing proofs in `cedar-spec` itself. The upstream project owns that work; this repository consumes `typeOf` as a black box.
- A published library package. This repository is a research workbench.

## Open questions

1. What fraction of Cedar's `Expr` grammar can the synthesis tactic of [1] cover without hand-written synthesis rules? Measured only on the shipped STLC benchmark so far.
2. Does the bridging `Prop`-wrapper over a functional typechecker scale beyond `typeOf` to the full env-check chain (requires + entity-store validation)?
3. What correctness claim applies to the generator? [2] gives a sound-and-complete derivation for inductive relations; [1] gives a support-based correctness for predicates. Whether the claim applicable here is distributional, support-based, or something weaker depends on the final form of `isWellTyped`'s rewriting.

## References

[1] *The Search for Constrained Random Generators.* PLDI 2026. https://arxiv.org/abs/2511.12253

[2] *Computing Correctly with Inductive Relations.* PLDI 2022. https://doi.org/10.1145/3519939.3523707
