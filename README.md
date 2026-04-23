# kairos-cedar

A reproducible workbench for synthesising Cedar policies from a Lean formalisation of the Cedar type system, with the aim of differentially testing production Cedar implementations on type-checking, evaluation, and symbolic compilation.

## Problem statement

Cedar [1] is a policy language for authorisation with a published Rust reference implementation [2] and an independent Go reimplementation [3]. A mechanised Lean specification of Cedar's type-checker, evaluator, and symbolic compiler (with machine-checked soundness and completeness proofs) is maintained at [4]. The existing differential testing pipeline described in [5] generates test inputs via byte-level arbitrary sampling; most generated inputs fail to type-check and are rejected early by the parser.

This repository builds the infrastructure for a type-directed alternative: a random generator that samples Cedar policies uniformly from the set of policies well-typed under a given environment. Such a generator concentrates sampling effort on semantically interesting inputs and produces richer differential-testing corpora.

## Approach

The generator is derived from the mechanised Lean type-checker of [4] following the program-synthesis technique of [6]. Where the type-checker is defined as a functional recursion, a `Prop`-valued shape wrapper is introduced so the proof-search tactic in [6] can invert it. An earlier formulation of the derivation for inductive relations appears in [7] (in Rocq rather than Lean).

The workbench integrates:

- The Lean 4 formalisation from [4] (`cedar-spec`) as a git submodule.
- The Palamedes Lean library from [6] (`palamedes-lean`) as a git submodule.
- The Rust reference implementation from [2] (`cedar` cloned under `cedar-spec/`).
- The Go reimplementation from [3] (`cedar-go`) as a git submodule, for differential testing.
- A shared oracle corpus from [8] (`cedar-integration-tests`) as a git submodule.

All toolchains are provided by a single container image at `ghcr.io/athanor-ai/kairos-cedar`: Lean 4.29.1 and 4.24.0 (via elan), Rust stable and nightly (for `cedar-policy` and Verus [9]), Go 1.24 (for `cedar-go`), Dafny 4.9.1 with bundled Z3 (for the symbolic-compilation track), and the Cedar CLI. No host installation is required.

## Repository layout

```
kairos-cedar/
  containers/Containerfile       one-image toolchain bundle
  containers/compose.yaml        dev wrapper (`docker compose`)
  scripts/dc                     `./scripts/dc <cmd>` runs inside the image
  scripts/preflight.py           environment sanity check
  cedar-spec-bridge/             Lake project: Prop-valued wrapper around
    CedarBridge/Predicates.lean    Cedar.Validation.typeOf from [4]
  cedar-micro/                   Lake project: minimal Cedar-shape type
    CedarMicro/{Ty,Expr,         system with Palamedes scaffolding per the
      WellTyped}.lean              pattern in [6]
  demo/                          deterministic end-to-end demo (no API use)
  docs/ARCHITECTURE.md           design decisions
  docs/ROADMAP.md                phased work plan
  tests/                         unit + IP-hygiene + integration tests
  cedar-spec/  palamedes-lean/   git submodules (upstream)
  cedar-go/    cedar-integration-tests/
```

## Reproduction

```
git clone --recurse-submodules https://github.com/athanor-ai/kairos-cedar.git
cd kairos-cedar
python3 scripts/preflight.py
docker pull ghcr.io/athanor-ai/kairos-cedar:latest
./scripts/dc bash -c 'cd cedar-spec-bridge && lake update && lake build'
./scripts/dc bash -c 'cd cedar-go && go test -run TestCorpus -count=1'
```

The first command clones all submodules. Preflight verifies the Docker daemon, compose v2, submodule checkout, disk space, and host architecture. The image pull is approximately 9 GB. The bridge build compiles the mechanised Cedar specification from [4] together with the `Prop`-wrapper defined in `cedar-spec-bridge/CedarBridge/Predicates.lean`. The final command runs the Go reimplementation's shipped corpus-test suite, which internally cross-checks each decision against the Rust reference via the bundled `cedar-validation-tool` harness.

## Current status (V0)

- Container image published and public.
- `cedar-spec-bridge` compiles against upstream `cedar-spec`; `isWellTyped env e := ∃ te c, typeOf e [] env = .ok (te, c)` is verified as the target shape for generator synthesis.
- `cedar-micro` contains a flat Cedar-shape type system (bool, int) with the Palamedes scaffolding of [6] ported from the STLC example distributed with Palamedes.
- `cedar-micro/CedarMicro/Expr.lean` has the five-constructor expression grammar (`litInt`, `litBool`, `var`, `ite`, `and`) without the recursive-case scaffolding. Completing this scaffolding is the open work item before `generator_search` can be invoked.
- See `docs/ROADMAP.md` for the phased plan through V3.

## References

[1] *Cedar: A New Language for Expressive, Fast, Safe, and Analyzable Authorisation.* OOPSLA 2024. `https://dl.acm.org/doi/10.1145/3649835`

[2] `cedar-policy/cedar`. `https://github.com/cedar-policy/cedar`

[3] `cedar-policy/cedar-go`. `https://github.com/cedar-policy/cedar-go`

[4] `cedar-policy/cedar-spec` (Lean mechanisation of Cedar). `https://github.com/cedar-policy/cedar-spec`

[5] *How We Built Cedar: A Verification-Guided Approach.* FSE 2024. `https://arxiv.org/abs/2407.01688`

[6] *The Search for Constrained Random Generators.* PLDI 2026. `https://arxiv.org/abs/2511.12253`. Code: `https://github.com/hgoldstein95/palamedes-lean`

[7] *Computing Correctly with Inductive Relations.* PLDI 2022. `https://doi.org/10.1145/3519939.3523707`

[8] `cedar-policy/cedar-integration-tests`. `https://github.com/cedar-policy/cedar-integration-tests`

[9] Verus: rust verification via SMT. `https://github.com/verus-lang/verus`

## License

MIT (see `LICENSE`). Copyright (c) 2026 Athanor AI, Inc.
