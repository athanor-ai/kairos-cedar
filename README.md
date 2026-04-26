# kairos-cedar

A type-directed differential-testing workbench for Cedar policy languages, built on top of the mechanised Lean specification.

Authorisation evaluators sit on the security-critical path: a soundness gap between two implementations of the same policy language is a privilege-escalation primitive. Cedar ships a Rust reference, a Go reimplementation, and a Lean mechanisation  - but the existing differential-testing pipeline samples policies via byte-level `arbitrary`, and most generated inputs are rejected by the parser before they ever reach the evaluator. This repository derives a generator from the Lean type-checker that samples uniformly from the set of well-typed policies, concentrating differential effort on inputs that actually exercise the semantics.

## Headline result

At $N = 10{,}000$ across 42 policy/request shapes (V1 + novelty sweep), the Rust reference (`cedar-policy` 4.3.1) and Go reimplementation (`cedar-go` HEAD) agree on every decision:

```
shapes              42
samples             10000
valid-rate          1.000
disagreements       0
ε (one-sided 95%)  ≤ 4.6 × 10⁻⁴   (Hoeffding)
median wall-time    0.015 s/tuple
```

See `experiments/phase_c_diff/run_diff.py` for the driver and `kairos-cedar-paper/` for the FMCAD-2026 write-up.

## Status

| Phase | Component | Status |
| :- | :- | :- |
| V1 | Container image (`ghcr.io/athanor-ai/kairos-cedar`) | ✅ published |
| V1 | `cedar-spec-bridge`  - `Prop`-wrapper over upstream `Cedar.Validation.typeOf` | ✅ |
| V1 | `cedar-micro`  - flat type system, `genWellTyped` + `Soundness` sorry-free | ✅ |
| V1 | `cedar-micro`  - `isWellTyped ↔ HasType` biconditional | ✅ |
| V2 | `cedar-full`  - full `Cedar.Spec.Expr` (12 constructors), `genSize_sound` 7-arm | ✅ sorry-free |
| V2 | `cedar-full/PolicyGen`  - 42 well-typed policy shapes + 27 request combinations | ✅ |
| V2 | Rust ↔ Go differential runner, $N = 10{,}000$, 0 disagreements | ✅ |
| V3 | Coverage-completeness theorem (sorry-free, branch `platform/cedar-drt-abac-type-directed`) | ✅ |
| V3 | Mutant-killing study vs. cedar-drt baseline (branch `platform/seeded-mutants-v2`) | ⏳ in progress |
| V4 | Symbolic-compilation track (Dafny + Z3) | ⏳ scaffolded |
| V4 | End-to-end fleet run with Supabase trace capture | ⏳ pending |

## Reproduce

```bash
git clone --recurse-submodules https://github.com/athanor-ai/kairos-cedar.git
cd kairos-cedar
python3 scripts/preflight.py
docker pull ghcr.io/athanor-ai/kairos-cedar:latest
./scripts/dc bash -c 'cd cedar-spec-bridge && lake update && lake build'
./scripts/dc python3 experiments/phase_c_diff/run_diff.py --n 10000
```

The first command clones all submodules. Preflight verifies the Docker daemon, Compose v2, submodule checkout, disk space, and host architecture. The image pull is approximately 9 GB. The bridge build compiles the mechanised Cedar specification from [cedar-spec](https://github.com/cedar-policy/cedar-spec) together with the `Prop`-wrapper defined in `cedar-spec-bridge/CedarBridge/Predicates.lean`. The final command runs the Go reimplementation's shipped corpus-test suite, which internally cross-checks each decision against the Rust reference via the bundled `cedar-validation-tool` driver.

## Where to look

| Question | File |
| :- | :- |
| What does soundness mean for the generator? | `cedar-full/CedarFull/Soundness.lean` |
| How is the typing relation defined? | `cedar-micro/CedarMicro/HasType.lean` |
| How is a well-typed policy generated? | `cedar-full/CedarFull/PolicyGen.lean` |
| What are the 42 policy shapes? | `cedar-full/CedarFull/PolicyGen.lean` (search `shape`) |
| How is the Rust ↔ Go diff run? | `experiments/phase_c_diff/run_diff.py` |
| What does the deterministic demo look like? | `demo/run_demo.py` |
| Architectural decisions / phased plan | `docs/ARCHITECTURE.md`, `docs/ROADMAP.md` |
| Coverage-completeness theorem | branch `platform/cedar-drt-abac-type-directed` |
| Mutant-killing study | branch `platform/seeded-mutants-v2` |

## Repository layout

```
kairos-cedar/
  containers/Containerfile         one-image toolchain bundle (Lean, Rust, Go, Dafny, Z3)
  containers/compose.yaml          dev wrapper (`docker compose`)
  scripts/dc                       `./scripts/dc <cmd>` runs inside the image
  scripts/preflight.py             environment sanity check
  cedar-spec-bridge/               Lake project: Prop-valued wrapper around upstream typeOf
  cedar-micro/                     Lake project: minimal Cedar-shape type system
  cedar-full/                      Lake project: full Cedar.Spec.Expr + 42 policy shapes
  experiments/phase_c_diff/        Rust ↔ Go differential runner
  demo/                            deterministic end-to-end demo (no API use)
  docs/ARCHITECTURE.md             design decisions
  docs/ROADMAP.md                  phased work plan through V4
  tests/                           unit, hygiene, integration tests
  cedar-spec/  palamedes-lean/     git submodules (upstream)
  cedar-go/    cedar-integration-tests/
```

## Acknowledgments

The mechanised Cedar specification and the Rust/Go implementations are the work of the [cedar-spec](https://github.com/cedar-policy/cedar-spec) maintainers (FSE 2024 [1]; OOPSLA 2024 [4]). The synthesis tactic `genSize_sound` and the `Prop`-wrapper pattern are from [palamedes-lean](https://github.com/hgoldstein95/palamedes-lean) (PLDI 2026 [2]). The earlier Rocq formulation for inductive relations comes from PLDI 2022 [3]. The byte-level `arbitrary` baseline we differentially compare against is the cedar-drt pipeline shipped with cedar-spec [1].

## References

[1] *How We Built Cedar: A Verification-Guided Approach.* FSE 2024. https://arxiv.org/abs/2407.01688

[2] *The Search for Constrained Random Generators.* PLDI 2026. https://arxiv.org/abs/2511.12253

[3] *Computing Correctly with Inductive Relations.* PLDI 2022. https://doi.org/10.1145/3519939.3523707

[4] *Cedar: A New Language for Expressive, Fast, Safe, and Analyzable Authorisation.* OOPSLA 2024. https://dl.acm.org/doi/10.1145/3649835

## License

MIT (see `LICENSE`). Copyright (c) 2026 Athanor AI, Inc.
