# kairos-cedar

Lean-verified, type-directed differential testing for the [Cedar][cedar-policy] authorisation engine. Surfaces real bugs in production implementations by running every sample through three independent oracles — the Rust reference (`cedar-policy`), the Go reimplementation (`cedar-go`), and the Lean-mechanised `cedar-spec` evaluator — with disagreements routed to a [`cedar-spec`][cedar-spec] source location that fixes the verdict.

## What's new (FMCAD 2026 submission)

**33 spec-source-attributed findings across three production artefacts**, surfaced by a generator whose every output is well-typed by construction (Lean soundness theorem, sorry-free).

| Artefact | Findings | Class |
|---|---|---|
| `cedar-go` 1.6.0 | 24 | 18 marshaller panics from one length-check elision (`cedar_marshal.go:199`), 4 schema round-trip drifts, 2 extension-literal parser drifts |
| `cedar symcc` (cedar-spec's symbolic compiler → CVC5 1.3.1) | 7 | one soundness bug in the `toDate`/`toTime` encoder (CVC5 returns a witness the concrete evaluator errors on); six undocumented encoder gaps |
| OPA Rego (8-shape Lean-mechanised subset, applied to OPA v1.15.2) | 2 | NAF / polymorphic-iteration semantics gaps |

Every finding cites a `cedar-spec` source location that fixes the verdict; the attribution function's totality is mechanised in Lean (`CedarBridge.Attribution.attribution_total`, sorry-free).

The same run also produces a quantitative equivalence bound: at N = 10,000 within the base grammar, the residual Rust↔Go disagreement rate is ≤ 4.6 × 10⁻⁴ at 95% confidence (Hoeffding). What the empirical run can't find is what the bound calibrates.

## How it works (kairos · Palamedes · LLMs are different things)

Mike Hicks' first review pass asked "what is the role of the kairos agents? I thought you used Palamedes." Answer:

- **kairos** is the **orchestrator** for the whole derive→verify→differential-run loop. It drives a configurable proposer, retries on each attributed bug, widens the generator into the next constructor class, and routes findings to spec-source-attributed reports. The kairos *contribution* is the verification scaffolding (the `isWellTyped` bridge + sorry-free soundness theorem) and the attribution function — not the proof-search itself.
- **Palamedes** ([PLDI 2026][palamedes]) is **one proposer**: a proof-search tactic that closes the generator-synthesis goal automatically given per-type scaffolding. It's the proposer that *works* on Cedar.
- **LLMs** are **another proposer**: three frontier models (Claude Sonnet 4.6, Claude Opus 4.6, Kimi K2.6) asked to emit the generator over Cedar's `Expr` type yield zero valid samples across 45 attempts. They hallucinate combinator names from the QuickCheck (Haskell) and QuickChick (Rocq) training-corpus surfaces — `Gen.map`, `Gen.oneOf`, `sized`, `chooseNat` — none of which Palamedes ships under that spelling. On a verifier surface absent from pretraining, the model inverts to its public-API priors regardless of iteration budget. **The contribution is the verification scaffolding that closes that gap, not the proposer.**

The proposer is pluggable by design. Soundness is independent of which proposer fires — it comes from the acceptance oracle.

## The three oracles

The differential runner takes each generated `(Policy, Schema, Request)` tuple and dispatches it to **three** independent implementations:

1. **`cedar-policy` 4.10.0** — the Rust reference, deployed at AWS. The definitive production implementation.
2. **`cedar-go` 1.6.0** — the independent Go reimplementation deployed at StrongDM. Tested at its `Authorize` entry point.
3. **`cedar-spec` evaluator** — the Lean-mechanised reference [cedar-spec][cedar-spec] maintains. Disagreement against this oracle is the strongest "spec drift" signal we can ship — Rust against the spec is the headline.

Rust↔Go disagreement is implementation drift between the two production engines. Rust↔Spec or Go↔Spec disagreement is spec drift. Both classes are caught.

> **Aside on the `arbitrary` baseline.** [cedar-drt][cedar-drt] (the closest published comparison) generates inputs by feeding random byte buffers into **hand-authored** `Arbitrary` instances over `Policy` / `Schema` / `Request`, with retry on parse failure. The instances aren't auto-derived. cedar-drt has found 21 real bugs and is the direct baseline for this work — most of its budget is consumed by the parser, leaving the evaluator largely untested.

## Architecture

```
                                                       ┌─ cedar-policy  (Rust)  ─┐
  Lean 4                       isWellTyped              │                          │
  ─────────────────────         (Prop wrapper           ├─ cedar-go      (Go)    ─┤
  proposer                      over typeOf)            │                          ├─→ spec-source
  • Palamedes (default)  ──→  ────────────  ──→  10k    ├─ cedar-spec    (Lean)  ─┤    attributed
  • LLMs (negative)                          tuples     │                          │    finding
  ─────────────────────                                 ├─ cedar symcc   (CVC5)  ─┤
  per-type scaffolding                                  │                          │
  Data/Cedar.Spec.Expr/                                 └─ OPA Rego     (OPA)    ─┘
                                                              ↑
                                                     widened generator
                                                     on each attributed bug
```

The two non-Rust/Go oracles (`cedar symcc`, OPA Rego) carry the symbolic-compilation track and the multi-DSL transferability track respectively. Both are Lean-mechanised: cedar symcc lowers Cedar to CVC5 with a soundness theorem; the Rego subset is `Rego.Spec.{Expr, HasType, Eval}` with sorry-free per-arm soundness.

## What's verified in Lean

| Component | Theorem | sorry-free? |
|---|---|---|
| `cedar-spec-bridge` | `isWellTyped ↔ ∃ te c, typeOf e [] env = .ok (te, c)` (the wrapper that lets Palamedes target a `def`-shaped typechecker as a `Prop`) | ✅ |
| `cedar-micro` (5 constructors: `litInt`, `litBool`, `var`, `ite`, `and`; 2 base types: `Int`, `Bool`) | Soundness (Theorem 1: every term in `genWellTyped`'s support is well-typed) + coverage (Theorem 2: support equals the well-typed terms in the literal palette) | ✅ |
| `cedar-full` (full `Cedar.Spec.Expr`, 12 constructors over 5 arity classes) | `isWellTyped_iff_hasType_full` biconditional + `genSize_sound` per-arm soundness across 12 constructors | ✅ |
| `CedarBridge.Attribution` | `attribution_total` — every disagreeing tuple maps to exactly one of `RUST-CORRECT` / `GO-CORRECT` / `BOTH-DIVERGE` | ✅ |
| Hoeffding bound | Theorem 3: zero disagreements at N → residual rate ≤ ln(1/δ)/N | ✅ |
| Rego subset (8 shapes) | per-arm soundness for `Rego.Spec.HasType` against `Rego.Spec.Eval` | ✅ |

CedarMicro is pedagogical-sized (5 constructors, depth ≤2). The headline run uses cedar-full at depth ≤6. Both ship sorry-free; the cedar-full lift is mechanised in `cedar-full/CedarFull/Soundness.lean`.

## Reproduce

```bash
git clone --recurse-submodules https://github.com/athanor-ai/kairos-cedar.git
cd kairos-cedar
python3 scripts/preflight.py
docker pull ghcr.io/athanor-ai/kairos-cedar:latest
./scripts/dc bash -c 'cd cedar-spec-bridge && lake update && lake build'
./scripts/dc python3 experiments/phase_c_diff/run_diff.py --n 10000
```

`preflight.py` checks Docker, Compose v2, submodule checkout, disk (~9 GB image pull), host arch. The bridge `lake build` compiles upstream `cedar-spec` (pinned via submodule) plus the `Prop`-wrapper from `cedar-spec-bridge/CedarBridge/Predicates.lean`. The final command runs the **three-oracle** differential runner: every tuple is sent to `cedar-policy` (Rust), `cedar-go` (Go), and the `cedar-spec` Lean evaluator; disagreements are minimised via delta-debugging and routed to the attribution function.

To reproduce specific findings:

```bash
# 18 cedar-go marshaller panics (B3 class)
./scripts/dc python3 experiments/phase_h_json_roundtrip/run.py

# 4 schema round-trip drifts (B1 class)
./scripts/dc python3 experiments/phase_i_schema_roundtrip/run.py

# 2 extension-literal parser drifts (B2 class)
./scripts/dc python3 experiments/phase_c_diff/run_diff.py --widen extension-literals

# 7 cedar symcc encoder gaps including one soundness bug (B4 class)
./scripts/dc python3 experiments/phase_j_symcc_sweep/run.py

# 2 OPA Rego semantics gaps (B5 class)
./scripts/dc python3 experiments/phase_k_opa_diff/run.py
```

The image embeds all three implementations + CVC5 1.3.1 + OPA v1.15.2 at the versions tested. No host toolchains required beyond Docker.

## Where to look

| Question | File |
|---|---|
| What's the verification scaffolding (the `isWellTyped` bridge)? | `cedar-spec-bridge/CedarBridge/Predicates.lean` |
| How is the Cedar typing relation defined? | `cedar-micro/CedarMicro/HasType.lean`, `cedar-full/CedarFull/HasType.lean` |
| How is generator soundness proved? | `cedar-full/CedarFull/Soundness.lean` (sorry-free, no `native_decide`, no external solver) |
| How are Policy/Schema/Request tuples generated? | `cedar-full/CedarFull/PolicyGen.lean` |
| How does the differential runner work? | `experiments/phase_c_diff/run_diff.py` |
| What does spec-source attribution mean? | `cedar-spec-bridge/CedarBridge/Attribution.lean` (totality theorem) |
| Where is the cedar symcc walkthrough? | `docs/symcc-walkthrough.md` |
| Where is the OPA Rego subset? | `experiments/phase_k_opa_diff/Rego/Spec/` |
| How is the Hoeffding bound applied? | `kairos-cedar-paper/main.tex` Theorem 3 + Appendix H |
| Architectural decisions / phased plan | `docs/ARCHITECTURE.md`, `docs/ROADMAP.md` |

## Repository layout

```
kairos-cedar/
  containers/Containerfile                 one-image toolchain bundle (Lean, Rust, Go, Dafny, CVC5, OPA)
  containers/compose.yaml                  dev wrapper (`docker compose`)
  scripts/dc                               run inside the image: ./scripts/dc <cmd>
  scripts/preflight.py                     environment sanity check
  cedar-spec-bridge/                       Lake project: Prop-wrapper around upstream typeOf + attribution
  cedar-micro/                             Lake project: pedagogical Cedar subset (5 ctors, 2 types)
  cedar-full/                              Lake project: full Cedar.Spec.Expr (12 ctors, 5 arity classes)
  experiments/phase_c_diff/                three-oracle differential runner
  experiments/phase_h_json_roundtrip/      cedar-go marshaller-panic class (B3, 18 cases)
  experiments/phase_i_schema_roundtrip/    cedar-go schema marshaller class (B1, 4 cases)
  experiments/phase_j_symcc_sweep/         cedar symcc encoder probe (B4, 7 cases incl. 1 soundness bug)
  experiments/phase_k_opa_diff/            OPA Rego cross-DSL probe (B5, 2 cases) + Lean Rego subset
  experiments/phase_a_v2/                  LLM-baseline negative result (3 frontier proposers, 0 valid samples)
  experiments/byte_fuzz_baseline/          standalone byte-level fuzz harness (parser-reach metric)
  examples/                                4 self-contained examples with run.sh
  demo/                                    deterministic end-to-end demo
  docs/ARCHITECTURE.md                     design decisions
  docs/ROADMAP.md                          phased plan
  docs/symcc-walkthrough.md                cedar symcc + CVC5 walkthrough
  cedar-spec/  palamedes-lean/             git submodules (upstream)
  cedar-go/    cedar-integration-tests/    git submodules (upstream)
```

## Acknowledgments

The mechanised Cedar specification, the Rust reference (`cedar-policy`), the Go reimplementation (`cedar-go`), and the byte-level [cedar-drt][cedar-drt] differential-testing pipeline are the work of the [cedar-spec][cedar-spec] maintainers (FSE 2024 [1]; OOPSLA 2024 [4]). The `genSize_sound` proof-search tactic and the `Prop`-wrapper pattern are from [palamedes-lean][palamedes-lean] (PLDI 2026 [2]). The earlier Rocq formulation for type-directed generator derivation comes from PLDI 2022 [3]. Without all four pieces of upstream infrastructure, none of this work would exist.

## References

[1] *How We Built Cedar: A Verification-Guided Approach.* FSE 2024. https://arxiv.org/abs/2407.01688

[2] *The Search for Constrained Random Generators.* PLDI 2026. https://arxiv.org/abs/2511.12253

[3] *Computing Correctly with Inductive Relations.* PLDI 2022. https://doi.org/10.1145/3519939.3523707

[4] *Cedar: A New Language for Expressive, Fast, Safe, and Analyzable Authorisation.* OOPSLA 2024. https://dl.acm.org/doi/10.1145/3649835

## Citation

If you use kairos-cedar in academic work:

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
[palamedes]: https://arxiv.org/abs/2511.12253
[palamedes-lean]: https://github.com/hgoldstein95/palamedes-lean
