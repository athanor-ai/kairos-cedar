# Architecture

## Single-image toolchain

The workbench composes artefacts from several upstream projects (see `README.md` references). Each upstream pins a different toolchain version:

| Component | Toolchain | Source |
| --- | --- | --- |
| `cedar-spec/cedar-lean` | Lean 4.29.1, `batteries` only | [4] |
| `palamedes-lean` | Lean 4.24.0, Mathlib, Aesop, Plausible | [6] |
| `cedar-policy` (Rust reference) | Rust stable 1.82+ | [2] |
| Verus (optional) | Rust nightly 1.94 | [9] |
| `cedar-go` | Go 1.24 | [3] |
| Dafny + Z3 (symbolic track) | Dafny 4.9.1, Z3 4.12.1 | Dafny project |
| Cedar CLI | `cedar-policy-cli` crate | [2] |

Host installation of the above is impractical due to conflicting global state (two `elan` profiles, two `rustup` toolchains, system-wide Go). The workbench installs all of them into a single container image, published at `ghcr.io/athanor-ai/kairos-cedar`. Toolchain selection inside the image is local: switch Lean via `elan default leanprover/lean4:<version>` per Lake project, invoke the appropriate rust toolchain via `cargo +<toolchain>`.

The `scripts/dc` wrapper shells a command into the image with the repository mounted at `/work`:

```
./scripts/dc lean --version
./scripts/dc cargo --version
./scripts/dc go version
./scripts/dc dafny --version
./scripts/dc cedar --version
```

## Lean bridge

`cedar-spec/cedar-lean` defines `Cedar.Validation.typeOf : Expr → Capabilities → TypeEnv → Except TypeError (TypedExpr × Capabilities)` as a functional `def`, not as an inductive relation. The derivation technique of [7] requires an inductive-`Prop` shape; the technique of [6] operates on predicates and handles the functional shape via rewrites.

To avoid forking `cedar-spec`, the bridge project at `cedar-spec-bridge/` imports the upstream package unchanged and adds `Prop`-valued wrappers:

```lean
def isWellTyped (env : TypeEnv) (e : Expr) : Prop :=
  ∃ te c, Cedar.Validation.typeOf e [] env = .ok (te, c)
```

Upstream updates are consumed by `git submodule update --remote cedar-spec`. The bridge is the single place where `cedar-spec` types are translated into the shape expected by the synthesis target.

## Two formal-methods track

The container image ships both Lean 4 and Verus [9]. A subset of Cedar's evaluator expressed in Verus-annotated Rust can be proved against a separately authored algebraic specification; the same subset is already proved against the Lean evaluator in [4] via the symbolic-compilation soundness theorem. If the Verus-derived verdicts disagree with Lean-derived verdicts on the same input, the divergence indicates a specification defect in at least one of the two formal models. No code on this track has been written yet; see `docs/ROADMAP.md`.

## Differential testing plan

The generator derived from the Lean formalisation emits policies and requests that, by construction, type-check and evaluate under the Lean semantics. The corpus is then executed against:

1. The Rust reference `cedar-policy` [2]: expected to agree on every input.
2. The Go reimplementation `cedar-go` [3]: expected to agree where feature support is declared (known gaps: schema validator, partial evaluation, policy templates as of v1.6.0).

Disagreements between (1) and (2) indicate a defect in at least one implementation or an ambiguity in the specification. The corpus from [8] shipped with `cedar-go v1.6.0` yields zero disagreements. New disagreements are expected on fresh, type-directed inputs, which is the motivation for the generator work.
