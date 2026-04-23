# kairos-cedar

**Synthesizing Cedar policies from a Lean formalization of the Cedar type system, so we can differentially test production Cedar implementations on type-checking, evaluation, and symbolic compilation.**

This repository is the reproducible workbench for the approach. The actual generator-derivation work is in progress; we're publishing the scaffolding now to invite collaboration from labs working on property-based testing of formal languages (Lampropoulos at UMD, Hicks at AWS, Torlak at UW, and others on Mailing/Pierce-line proof-search for PBT).

## The goal

Given AWS's [`cedar-spec`](https://github.com/cedar-policy/cedar-spec) — a Lean 4 mechanization of Cedar's type checker, evaluator, and symbolic compiler, with soundness + completeness proofs — we want a random generator that samples Cedar policies uniformly from *the set of well-typed-under-environment `Γ` policies*. Such a generator is strictly stronger than AWS's existing `cedar-policy-generators` crate (which uses `arbitrary` over byte strings, producing many ill-typed drafts), because it exercises the deep parts of the type system the reference implementation wants to be trusted on.

The technique comes from two papers:

- **Paraskevopoulou / Eline / Lampropoulos, *Computing Correctly with Inductive Relations*, PLDI '22** — [pdf](https://lemonidas.github.io/pdf/ComputingCorrectly.pdf). Given an inductive relation `P : T₁ → … → Prop`, derive a random generator that produces values satisfying `P`, plus a machine-checked correctness proof. Implemented in Rocq / QuickChick.
- **Goldstein / Peleg / Torczon / Sainati / Lampropoulos / Pierce, *The Search for Constrained Random Generators*, PLDI '26** — [arxiv](https://arxiv.org/abs/2511.12253), [code](https://github.com/hgoldstein95/palamedes-lean). Tool: **Palamedes**. Lean-native, uses Aesop proof search over a denotational semantics of generators; recursive predicates via catamorphism → anamorphism rewrite. More automated than the PLDI '22 recipe; fewer papers to translate by hand.

Cedar's typechecker is a `def` (not an `inductive ... → Prop`), so the PLDI '22 technique needs a Prop-shape wrapper before the derivation fires; Palamedes handles predicates directly, so it's a closer fit. Either path needs a companion-functor + recursion-scheme port of Cedar's `Expr` (Palamedes's existing `Data/STLC/` is ~1400 LOC of the pattern to mirror).

## What's in this repo today

This is V0 — infrastructure + a minimum-viable Lean bridge. The generator itself is the V1/V2 deliverable.

```
kairos-cedar/
├── containers/                 Docker pins for every toolchain we use
│   ├── spec.Containerfile      Lean 4.29.1 + batteries (cedar-spec)
│   ├── palamedes.Containerfile Lean 4.24.0 + Mathlib + Palamedes prewarmed
│   ├── rust-verus.Containerfile Rust 1.82 + 1.94 + Verus 0.2026.03.28
│   └── compose.yaml            Dev wrapper around `docker compose run`
├── scripts/
│   ├── dc                      Thin wrapper: `./scripts/dc <svc> <cmd>`
│   └── preflight.py            Sanity-check before you build
├── cedar-spec-bridge/          Lean 4 Lake project, Prop-valued wrapper around
│   └── CedarBridge/            cedar-spec's `Cedar.Validation.typeOf` — the
│       └── Predicates.lean     `isWellTyped` predicate Palamedes can target
├── docs/
│   ├── ARCHITECTURE.md         Why docker-first, why Lean bridges, why both
│   └── ROADMAP.md              V0 → V1 → V2 → V3 progression + open problems
├── .github/workflows/ci.yml    Preflight + container build on push
└── cedar-spec/                 } submodules — pinned upstream
    palamedes-lean/             }
    cedar-go/                   }
    cedar-integration-tests/    }
```

Everything is containerized. No toolchain on the host — that's deliberate so reproducibility is trivial across labs.

## Quick start

```bash
# 1. Clone with submodules
git clone --recurse-submodules https://github.com/athanor-ai/kairos-cedar.git
cd kairos-cedar

# 2. Preflight
python3 scripts/preflight.py
#   checks docker daemon, compose V2, submodules, disk, arch

# 3. Build the main containers (rust-verus is ~3 min, spec is ~4 min;
#    palamedes is ~15 min because Mathlib prewarms in-image — skip
#    unless you're on the V3 track)
docker compose -f containers/compose.yaml build spec rust-verus

# 4. Smoke the Lean bridge (compiles the CedarBridge Lake project
#    against upstream cedar-spec; exercises the isWellTyped wrapper)
./scripts/dc spec bash -c 'cd /work/cedar-spec-bridge && lake update && lake build'
#   Expected: 92 jobs green; CedarBridge.Predicates + CedarBridge compiled.

# 5. Validate cedar-go passes its shipped oracle (Rust↔Go baseline;
#    0 divergence on 7759 subtests at cedar-go v1.6.0)
./scripts/dc go bash -c 'cd /work/cedar-go && go test -run TestCorpus -count=1'
```

## Where the research is

- [`cedar-spec-bridge/CedarBridge/Predicates.lean`](cedar-spec-bridge/CedarBridge/Predicates.lean) is the shape-bridge from `def Cedar.Validation.typeOf` to a `Prop`-valued `isWellTyped env e := ∃ te c, typeOf e [] env = .ok (te, c)`. That's the target Palamedes's `generator_search` tactic inverts.
- The generator derivation itself is not yet written. The open problem is port Cedar's `Expr` inductive into the companion-functor + recursion-scheme shape Palamedes's existing `Data/STLC/` uses — approximately 1400 LOC of mostly-mechanical Lean scaffolding, plus `as_or` / `deforest_eq` lemmas per constructor.
- Toolchain mismatch: cedar-spec is Lean 4.29.1 + batteries; Palamedes is Lean 4.24.0 + Mathlib. We keep them in separate containers for now. A bump of Palamedes onto 4.29.1 + mathlib-4.29.x is probably the cleanest long-term fix; we haven't attempted it.
- We have not yet measured whether Palamedes's Aesop tactic can make progress on a non-trivial Cedar-shape predicate. The `STLC/WellTyped` benchmark works (5-line invocation, tractable terms fall out); the Cedar-micro smoke (`litInt / litBool / var / ite / and`) fails at Aesop because the per-type scaffolding isn't present. That scaffolding is the next piece of real work.

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the phased plan.

## Why differential testing

AWS already did Rust↔Lean DRT as part of the Cedar development process and found 21 bugs ([Cutler et al., *How We Built Cedar: A Verification-Guided Approach*, FSE '24](https://arxiv.org/abs/2407.01688)). Two observations drive the follow-on work here:

1. **The existing DRT uses `arbitrary` over bytes.** Most of the policies generated are ill-typed and die in the parser. A type-directed generator concentrates budget on semantically interesting policies.
2. **Rust ↔ Go is unscooped.** [`cedar-go`](https://github.com/cedar-policy/cedar-go) is the only production-grade independent reimplementation (Java is an FFI, WASM is compiled from Rust). Differential testing cedar-go against the Rust reference *with a type-directed corpus* is a fresh experiment whose outcome we don't know yet.

A positive outcome (agreement on 10⁴+ fresh policies) is a strong validation of both implementations' faithfulness to the spec. A negative outcome (a divergence) is a publishable bug.

## Collaboration

This is explicitly an invitation. If you're working on:

- **property-based testing of formal languages** (QuickChick, Plausible, Palamedes lineage)
- **Cedar** or related production authorization engines (AWS, Permify, OpenFGA, etc.)
- **differential / metamorphic testing of verified compilers** (Torlak / Rosette, Hicks, et al.)
- **Rust verification tooling** (Verus, Creusot, Kani) — the `rust-verus` container is wired in because we expect Verus-annotated subsets of the evaluator to compose nicely with the Lean side (see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#two-formal-methods))

…file an issue, open a draft PR, or email us. Happy to share intermediate data, prompts, or workspace state.

## Caveats

- **Still V0.** The generator derivation is not done. APIs of the bridge module may change. The Palamedes track blocks on the companion-functor port of Cedar's `Expr`.
- **Lean toolchain mismatch.** cedar-spec (4.29.1) and Palamedes (4.24.0) can't live in one Lake project as-is. We keep them in separate containers; a real Palamedes-on-4.29.1 fork is on the roadmap.
- **x86_64 only.** Verus ships a pre-built binary only for `x86-linux`. If you're on Apple Silicon, run the container on an x86_64 VM.
- **cedar-go TestCorpus passes 7759/7759 as of v1.6.0 on the embedded oracle.** The shipped corpus will not find you bugs; you need fresh-corpus generation for that, which is what this whole repo is building toward.

## Citation

No paper yet. If you build on the scaffolding here, please cite the two upstream papers linked above and a pointer back to this repo.

## License

MIT. See [LICENSE](LICENSE).

Copyright © 2026 Athanor AI, Inc. Maintained by the [Athanor AI](https://www.athanor-ai.com) team (`kairos` SDK group).
