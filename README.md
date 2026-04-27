# kairos-cedar

Lean-verified, type-directed differential testing for the [Cedar][cedar-policy] authorisation engine.

Each generated `(Policy, Schema, Request)` tuple is well-typed by construction (sorry-free Lean soundness theorem) and is dispatched to three independent oracles: the Rust reference (`cedar-policy`), the Go reimplementation (`cedar-go`), and the Lean-mechanised `cedar-spec` evaluator. Disagreements are minimised via delta debugging and routed to a `cedar-spec` source location that fixes the verdict.

## Findings

33 spec-source-attributed findings across three production artefacts:

| Artefact | Findings | Class |
|---|---|---|
| `cedar-go` 1.6.0 | 24 | 18 marshaller panics from one length-check elision (`cedar_marshal.go:199`); 4 schema round-trip drifts; 2 extension-literal parser drifts |
| `cedar symcc` (cedar-spec's symbolic compiler to CVC5 1.3.1) | 7 | one soundness bug in the `toDate`/`toTime` encoder; six undocumented encoder gaps |
| OPA Rego (8-shape Lean-mechanised subset, OPA v1.15.2) | 2 | NAF and polymorphic-iteration semantics gaps |

The attribution function's totality is mechanised in Lean (`CedarBridge.Attribution.attribution_total`, sorry-free).

At N = 10,000 within the base grammar, the residual Rust vs Go disagreement rate is at most 4.6 x 10^-4 at 95% confidence (Hoeffding).

## Architecture

```
                                            cedar-policy  (Rust)
  Lean 4
  ----------------------                    cedar-go      (Go)
  proposer (Palamedes)
            |              isWellTyped
            v   genWellTyped --> 10,000     cedar-spec    (Lean evaluator)        spec-source
                                tuples                                       --> attributed
  per-type scaffolding                                                            finding
  Data/Cedar.Spec.Expr/                     cedar symcc   (Cedar -> CVC5)
                                                  ^
                                          generator widened
                                          on each finding         OPA Rego     (OPA engine)
```

The orchestration loop (`derive` -> `verify` -> `differential run` -> `widen on attributed bug`) is driven by the kairos package. Palamedes is the default proposer; LLMs are an alternative proposer that fails on this surface (see [Negative result: LLM proposer](#negative-result-llm-proposer)). The proposer is pluggable; soundness is independent of it and comes from the acceptance oracle.

## What is verified in Lean

| Component | Theorem | sorry-free |
|---|---|---|
| `cedar-spec-bridge` | `isWellTyped <-> exists te c, typeOf e [] env = .ok (te, c)` | yes |
| `cedar-micro` (5 constructors, 2 base types: pedagogical) | Soundness (every term in support is well-typed) and coverage (support equals the well-typed terms in the literal palette) | yes |
| `cedar-full` (12 constructors, 5 arity classes) | `isWellTyped_iff_hasType_full` biconditional and `genSize_sound` per-arm soundness across 12 constructors | yes |
| `CedarBridge.Attribution` | `attribution_total`: every disagreeing tuple maps to exactly one of `RUST-CORRECT`, `GO-CORRECT`, `BOTH-DIVERGE` | yes |
| Rego subset (8 shapes) | per-arm soundness for `Rego.Spec.HasType` against `Rego.Spec.Eval` | yes |

Headline runs use `cedar-full` at depth at most 6. CedarMicro is reference-sized: five constructors (`litInt`, `litBool`, `var`, `ite`, `and`) over `Int` and `Bool`, used for the pedagogical worked example.

## Quickstart

```bash
git clone --recurse-submodules https://github.com/athanor-ai/kairos-cedar.git
cd kairos-cedar
python3 scripts/preflight.py
docker pull ghcr.io/athanor-ai/kairos-cedar:latest
./scripts/dc bash -c 'cd cedar-spec-bridge && lake update && lake build'
./scripts/dc python3 experiments/phase_c_diff/run_diff.py --n 10000
```

`preflight.py` checks Docker, Compose v2, submodule checkout, ~9 GB disk for the image pull, and host arch. The bridge `lake build` compiles upstream `cedar-spec` (pinned via submodule) plus the Prop wrapper at `cedar-spec-bridge/CedarBridge/Predicates.lean`. The final command runs the three-oracle differential runner.

The image bundles `cedar-policy` 4.10.0, `cedar-go` 1.6.0, the `cedar-spec` toolchain, CVC5 1.3.1, and OPA v1.15.2 at the versions tested. No host toolchains required beyond Docker.

### Reproduce a specific finding class

```bash
# 18 cedar-go marshaller panics (B3)
./scripts/dc python3 experiments/phase_h_json_roundtrip/run.py

# 4 schema round-trip drifts (B1)
./scripts/dc python3 experiments/phase_i_schema_roundtrip/run.py

# 2 extension-literal parser drifts (B2)
./scripts/dc python3 experiments/phase_c_diff/run_diff.py --widen extension-literals

# 7 cedar symcc encoder gaps including 1 soundness bug (B4)
./scripts/dc python3 experiments/phase_j_symcc_sweep/run.py

# 2 OPA Rego semantics gaps (B5)
./scripts/dc python3 experiments/phase_k_opa_diff/run.py
```

## Negative result: LLM proposer

Three frontier proposers (Anthropic Claude Sonnet 4.6, Anthropic Claude Opus 4.6, Moonshot Kimi K2.6) asked to emit the generator over Cedar's `Expr` type yield zero valid samples across 45 attempts. Each model hallucinates Palamedes combinator names from the QuickCheck (Haskell) and QuickChick (Rocq) training-corpus surfaces (`Gen.map`, `Gen.oneOf`, `sized`, `chooseNat`), none of which Palamedes ships under that spelling. On a verifier surface absent from pretraining, the model inverts to its public-API priors regardless of iteration budget.

The contribution of this work is the verification scaffolding that closes that gap, not the proposer. See `experiments/phase_a_v2/` for the full per-iteration log.

## Where to look

| Question | File |
|---|---|
| Verification scaffolding (the `isWellTyped` bridge) | `cedar-spec-bridge/CedarBridge/Predicates.lean` |
| Cedar typing relation | `cedar-micro/CedarMicro/HasType.lean`, `cedar-full/CedarFull/HasType.lean` |
| Generator soundness proof | `cedar-full/CedarFull/Soundness.lean` |
| Policy/Schema/Request tuple generator | `cedar-full/CedarFull/PolicyGen.lean` |
| Differential runner | `experiments/phase_c_diff/run_diff.py` |
| Spec-source attribution function | `cedar-spec-bridge/CedarBridge/Attribution.lean` |
| cedar symcc walkthrough | `docs/symcc-walkthrough.md` |
| OPA Rego subset | `experiments/phase_k_opa_diff/Rego/Spec/` |
| Architectural decisions | `docs/ARCHITECTURE.md`, `docs/ROADMAP.md` |

## Repository layout

```
kairos-cedar/
  containers/Containerfile              one-image toolchain (Lean, Rust, Go, CVC5, OPA)
  containers/compose.yaml               dev wrapper for docker compose
  scripts/dc                            run inside the image: ./scripts/dc <cmd>
  scripts/preflight.py                  environment sanity check
  cedar-spec-bridge/                    Lake project: Prop wrapper around upstream typeOf, attribution
  cedar-micro/                          Lake project: pedagogical Cedar subset
  cedar-full/                           Lake project: full Cedar.Spec.Expr
  experiments/phase_c_diff/             three-oracle differential runner
  experiments/phase_h_json_roundtrip/   cedar-go marshaller-panic class (B3)
  experiments/phase_i_schema_roundtrip/ cedar-go schema marshaller class (B1)
  experiments/phase_j_symcc_sweep/      cedar symcc encoder probe (B4)
  experiments/phase_k_opa_diff/         OPA Rego cross-DSL probe (B5) and Lean Rego subset
  experiments/phase_a_v2/               LLM-baseline negative result
  experiments/byte_fuzz_baseline/       standalone byte-level fuzz harness
  examples/                             4 self-contained examples with run.sh
  demo/                                 deterministic end-to-end demo
  docs/ARCHITECTURE.md                  design decisions
  docs/ROADMAP.md                       phased plan
  docs/symcc-walkthrough.md             cedar symcc and CVC5 walkthrough
  cedar-spec/                           upstream Cedar specification (submodule)
  palamedes-lean/                       upstream Palamedes proposer (submodule)
  cedar-go/                             upstream Go reimplementation (submodule)
  cedar-integration-tests/              upstream conformance suite (submodule)
```

## Acknowledgements

The mechanised Cedar specification, the Rust reference (`cedar-policy`), the Go reimplementation (`cedar-go`), and the [cedar-drt][cedar-drt] differential-testing pipeline are the work of the [cedar-spec][cedar-spec] maintainers (FSE 2024 [1]; OOPSLA 2024 [4]). The `genSize_sound` proof-search tactic and the Prop wrapper pattern are from [palamedes-lean][palamedes-lean] (PLDI 2026 [2]). The earlier Rocq formulation for type-directed generator derivation is from PLDI 2022 [3].

## References

[1] *How We Built Cedar: A Verification-Guided Approach.* FSE 2024. https://arxiv.org/abs/2407.01688

[2] *The Search for Constrained Random Generators.* PLDI 2026. https://arxiv.org/abs/2511.12253

[3] *Computing Correctly with Inductive Relations.* PLDI 2022. https://doi.org/10.1145/3519939.3523707

[4] *Cedar: A New Language for Expressive, Fast, Safe, and Analyzable Authorisation.* OOPSLA 2024. https://dl.acm.org/doi/10.1145/3649835

## Citation

```bibtex
@misc{kairos_cedar_2026,
  title  = {kairos-cedar: Lean-Verified Differential Testing for the Cedar Authorisation Engine},
  author = {Yang, Aidan Z. H. and Hong, Samantha S. K. and {Athanor-AI}},
  year   = {2026},
  url    = {https://github.com/athanor-ai/kairos-cedar},
  note   = {Apache-2.0}
}
```

## License

Apache-2.0. See `LICENSE`. Copyright 2026 Athanor AI, Inc.

[cedar-policy]: https://github.com/cedar-policy/cedar
[cedar-spec]: https://github.com/cedar-policy/cedar-spec
[cedar-drt]: https://github.com/cedar-policy/cedar-spec/tree/main/cedar-drt
[palamedes-lean]: https://github.com/hgoldstein95/palamedes-lean
