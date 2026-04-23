# Roadmap

## V0 — infrastructure (this commit)

- [x] Containerized pins for every toolchain (Lean 4.29.1 + 4.24.0, Rust 1.82/1.94, Verus 0.2026.03.28, Go 1.24)
- [x] Git submodules for upstream: cedar-spec, palamedes-lean, cedar-go, cedar-integration-tests
- [x] Minimum-viable Lean bridge: `CedarBridge.isWellTyped env e` as a `Prop`-valued wrapper around cedar-spec's `def Cedar.Validation.typeOf`
- [x] Preflight script, thin dev wrapper `scripts/dc`, CI runs preflight + spec container build
- [x] Baseline observation: cedar-go v1.6.0 passes 7759/7759 of its shipped corpus (zero Rust↔Go divergence on the oracle)

## V1 — Palamedes on Cedar-micro

Prove the generator-derivation approach works on a small Cedar subset before scaling to the full `Expr`.

- [ ] Cedar-micro type system: `Expr := litInt | litBool | var | ite | and` + `Ty := int | bool`. Roughly 150 LOC Lean, fits entirely inside the palamedes container (4.24.0 + Mathlib). This sidesteps the cedar-spec toolchain mismatch for the proof-of-concept.
- [ ] Port the ~1400 LOC of `Palamedes/Data/STLC/` recursion-scheme scaffolding (`TyF α` companion functor, `as_or` / `deforest_eq` lemmas, `fold` / `accuM`) to the Cedar-micro shape.
- [ ] Invoke `generator_search` against `isWellTyped` for Cedar-micro. Verify Aesop makes progress, not "made no progress" (the symptom when scaffolding is absent).
- [ ] Sample 10⁴ well-typed Cedar-micro expressions, histogram depth + constructor frequency.

## V2 — Palamedes on full Cedar `Expr`

- [ ] Fork palamedes-lean, bump toolchain to 4.29.1 + mathlib-4.29.x. Submit upstream PR when green. (Alternative fallback: keep Palamedes on 4.24 and hand-copy the type-system modules from cedar-spec into a 4.24-compatible project. Uglier but unblocks parallel work if the bump is heavy.)
- [ ] Port cedar-spec's `Cedar.Spec.Expr` into the companion-functor shape. 12 constructors; likely 2–3x the STLC scaffolding in LOC. Focus on the ones the typechecker actually cases on; defer extension types (`call`) until last.
- [ ] Re-derive `isWellTyped` using the full `Cedar.Validation.typeOf`. Verify generator_search closes the goal.
- [ ] Differential test: sample 10⁵ policies, run through both cedar-policy (Rust) and cedar-go, log disagreements.

## V3 — Beyond type checking

Cedar has three semantic tiers the generator can target; V1/V2 cover the type-checker only.

- [ ] Evaluation: generate policies + entity stores + requests such that `cedar-policy::authorize` returns `Allow`; differentially test cedar-go on the same fixture.
- [ ] Symbolic compilation: generate policies compatible with cedar-spec's `Cedar.SymCC.Compiler`; test the SMT encoding against the concrete evaluator's verdict on matched requests.
- [ ] Hybrid: one generator emits a single `(policy, schema, request)` tuple triply-consistent across all three tiers, so any impl that disagrees on any tier is flagged.

## Ongoing — Rust verification tooling (Verus)

The `rust-verus` container ships with [Verus](https://github.com/verus-lang/verus) 0.2026.03.28 (Rust nightly 1.94) because we expect two lines of work:

- [ ] **Diff-harness correctness.** Verus-annotate the Rust harness that compares cedar-policy vs cedar-go per case. `requires`/`ensures` on the comparator, invariants on the aggregation. Small, defensible — puts Verus on the fleet-critical path with near-zero risk.
- [ ] **Two-formal-methods differential.** Verus-prove a subset of cedar-policy's evaluator against an algebraic spec; compare the Verus-derived verdicts against cedar-spec's Lean-derived verdicts on the same inputs. If Lean and Verus disagree on what a policy's behaviour should be, we've found either a Lean-spec bug, a Verus-proof bug, or an impl bug — all publishable.

## Out of scope

- Hosting a long-running fuzz job. Integrate this with `cargo fuzz` or a managed service if you need one.
- Closing Lean proofs in cedar-spec itself. That's upstream's job; we consume `typeOf` as a black box.
- Shipping a PyPI / crates.io package. This repo is a research workbench, not a library.

## Open questions

1. How close can Palamedes's Aesop tactic get on Cedar's actual `Expr` without hand-written synthesis rules? We haven't measured. STLC works out of the box; Cedar is materially more complex (records, sets, extension types).
2. Do we need the full type environment to be inductive, or does Palamedes handle `def`-based checkers with a thin Prop wrapper? The wrapper works for us on `typeOf` already; whether it scales to the full env-check chain is V2 work.
3. What's the right correctness proof for the *generator*? The PLDI '22 derivation gives you sound+complete automatically. Palamedes (per the paper) has a weaker correctness story (supports-based, not distributional). For differential testing either is sufficient, but for a paper claim we'd want to pin it down.
