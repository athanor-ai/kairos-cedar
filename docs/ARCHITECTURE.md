# Architecture

## Why one image

Every toolchain in this repo has a version pin that disagrees with at least one other:

| Tool                 | Pin                                      | Why                                   |
| -------------------- | ---------------------------------------- | ------------------------------------- |
| Lean (cedar-spec)    | 4.29.1 + batteries                       | cedar-spec's `lean-toolchain`         |
| Lean (palamedes)     | 4.24.0 + Mathlib + Aesop + Plausible     | palamedes-lean's `lean-toolchain`     |
| Rust                 | 1.82 stable + 1.94 nightly               | Cedar on stable, Verus on nightly     |
| Verus                | 0.2026.03.28 binary                      | matches the nightly above             |
| Go                   | 1.24                                     | cedar-go's `go.mod` minimum           |
| Dafny + Z3           | Dafny 4.9.1 (ships Z3)                   | symbolic-compilation diff track       |
| Cedar CLI            | v4.3.1+ via `cargo install`              | Rust reference implementation         |

You cannot build all of these on a host without a combinatorial mess of PATH juggling, virtualenvs, and rustup overrides. Our single image (`containers/Containerfile`) installs all of them side-by-side — `elan` ships two Lean toolchains, `rustup` ships two Rust toolchains, everything else sits at `/usr/local/bin`. The `scripts/dc` wrapper keeps the dev UX similar to a native invocation:

```bash
./scripts/dc lean --version            # default: 4.29.1
./scripts/dc bash -c 'elan default leanprover/lean4:v4.24.0 && lean --version'  # swap
./scripts/dc cargo --version
./scripts/dc verus --version
./scripts/dc go version
./scripts/dc dafny --version
./scripts/dc cedar --version
```

The monolith costs ~12 GB and ~25 min to build locally; we publish it to [`ghcr.io/athanor-ai/kairos-cedar`](https://github.com/athanor-ai/kairos-cedar/pkgs/container/kairos-cedar) so most users `docker pull` it once (~2 min on a reasonable connection) and never rebuild.

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
