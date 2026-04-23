# Architecture

## Why docker-first

Every toolchain in this repo has a version pin that disagrees with at least one other:

| Container              | Toolchain                                | Why                                   |
| ---------------------- | ---------------------------------------- | ------------------------------------- |
| `cedar-spec:dev`       | Lean 4.29.1 + batteries                  | cedar-spec's `lean-toolchain` pin     |
| `cedar-palamedes:dev`  | Lean 4.24.0 + Mathlib + Plausible + Aesop | palamedes-lean's `lean-toolchain` pin |
| `cedar-rust-verus:dev` | Rust 1.82 stable + 1.94 nightly + Verus 0.2026.03.28 | Cedar builds on stable; Verus requires its pinned nightly |
| `golang:1.24-bookworm` | Go 1.24                                  | cedar-go's `go.mod` minimum           |

You cannot build all of these on a single host without a combinatorial mess of PATH juggling, virtualenvs, and rustup overrides. Containerizing eliminates that. The thin `scripts/dc` wrapper keeps the dev UX similar to a native `lake`/`cargo`/`go` invocation:

```bash
./scripts/dc spec lake build Cedar
./scripts/dc rust-verus cargo build --release
./scripts/dc go go test -run TestCorpus -count=1
```

This also means customers of anything downstream of this repo — including the closed-source kairos SDK vertical at Athanor AI — pull pinned images rather than reproducing build environments. `docker run --rm ghcr.io/athanor-ai/cedar-spec:<date>` is all you need.

## Why a Lean bridge

cedar-spec's `Cedar.Validation.typeOf` is a `def`, not an `inductive ... → Prop`. The Paraskevopoulou/Lampropoulos '22 derivation technique wants an inductive relation so it can enumerate derivation trees. Palamedes is more forgiving — it works on predicates — but the idiomatic invocation still wants `Prop`-valued shapes.

`cedar-spec-bridge/` is a thin Lake subproject that depends on cedar-spec and adds:

```lean
def isWellTyped (env : TypeEnv) (e : Expr) : Prop :=
  ∃ te c, Cedar.Validation.typeOf e [] env = .ok (te, c)
```

`typeOf` is unchanged. We never fork cedar-spec; we compose with it. That keeps upstream updates cheap — `git submodule update` and we pick up AWS's latest.

The bridge is only ~30 lines today. It will grow as we add similar wrappers for `Cedar.Validation.validateSchema`, `Cedar.Spec.isAuthorized`, and the symbolic-compilation soundness lemma.

## Two formal methods (optional track)

The `rust-verus` container isn't just for running the cedar-policy reference implementation. It also ships [Verus](https://github.com/verus-lang/verus), so we can do an experiment the Cedar team has not published on: annotate a Rust subset of the evaluator with Verus `requires`/`ensures`, prove it against an independent algebraic spec, and compare the Verus-derived verdicts against cedar-spec's Lean-derived verdicts on the same inputs.

If Lean and Verus ever disagree about what a Cedar expression should evaluate to, we've found something interesting: either the Lean model has a bug, the Verus spec has a bug, or the implementation has a bug that slipped past both. Any of those is publishable.

See the [roadmap](./ROADMAP.md) for the phased plan.

## Generator derivation lineage

Two papers, both by groups we want to invite to collaborate:

1. **Paraskevopoulou / Eline / Lampropoulos, *Computing Correctly with Inductive Relations*, PLDI '22.** Given an inductive relation `P`, derive a QuickChick-compatible random generator for values satisfying `P`, plus a mechanized soundness/completeness proof. Implemented in Rocq as a plugin + Ltac2 metaprogramming. Strong correctness story. Requires the relation to be in inductive-Prop form and covers a specific grammar of constructor shapes (the paper details the extensions for non-linear patterns, function calls in conclusions, and existentials).

2. **Goldstein / Peleg / Torczon / Sainati / Lampropoulos / Pierce, *The Search for Constrained Random Generators*, PLDI '26.** Tool: **Palamedes**. Given a predicate (not necessarily inductive), synthesize a constrained random generator via Aesop proof search over a denotational semantics of generators. Handles recursive predicates by rewriting catamorphism-shaped predicates to anamorphism-shaped generators. Lean-native. More automated but weaker correctness guarantee (support-based, not distributional).

We pick Palamedes as the primary V1 target for two reasons: (a) Cedar's `typeOf` is a `def` / catamorphism shape that matches Palamedes's recursive-predicate handling, and (b) Palamedes is already Lean — no Rocq-to-Lean port of the tactic infrastructure. We keep `cedar-palamedes:dev` as a separate container so we can iterate on the V3 (generator-derivation) track in parallel with the V1 (workbench + differential testing scaffolding) track.

If Palamedes's Aesop proof search fails to make progress on Cedar's full `Expr` (it may — our `CedarMicro` smoke fails at Aesop until per-type `as_or`/`deforest_eq` lemmas are registered), we fall back to the PLDI '22 recipe, implemented manually in Lean metaprogramming. That's more work but we know it's possible.
