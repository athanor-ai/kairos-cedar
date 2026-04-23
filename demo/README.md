# kairos-cedar end-to-end demo

A deterministic, reproducible smoke of the kairos-cedar workbench. No LLM calls, no paid APIs, no network after the image pull. Total runtime is approximately 35 seconds once the image is cached locally.

## What it runs

1. **Lean bridge compiles.** `lake build` the `cedar-spec-bridge` Lake project inside the container image, which imports upstream [cedar-spec](https://github.com/cedar-policy/cedar-spec) and proves our `isWellTyped env e := ∃ te c, Cedar.Validation.typeOf e [] env = .ok (te, c)` wrapper compiles against the real mechanised type-checker. ~5 s with the Lake cache warm.

2. **Rust CLI decisions vs hand-authored expectations.** Six requests against a three-policy RBAC set (admin allow, forbid on confidential resources, editor-owns-resource) driven through the Rust `cedar authorize` CLI. Each decision is compared to a hand-authored expected label. Exercises `permit`/`forbid` precedence, role hierarchy, attribute conditions, and the `is` type guard. ~7 s.

3. **Generator synthesis.** Ten bool-typed + ten int-typed Cedar-micro expressions are sampled from the type-directed generator in `cedar-micro/CedarMicro/WellTyped.lean`. Each expression is runtime-verified against the functional typechecker `getType`. Every sampled expression satisfies `isWellTyped Γ` by construction. This is the core research artefact: a generator that produces only semantically meaningful inputs, rather than byte-level random data. ~2 s.

4. **Shipped corpus at scale.** `go test -run TestCorpus -count=1` inside cedar-go, which internally cross-checks each decision against the Rust reference via the bundled `test/cedar-validation-tool` harness on approximately 7760 subtests drawn from [cedar-integration-tests](https://github.com/cedar-policy/cedar-integration-tests). ~11 s.

Combined, the demo produces four independent signals: (1) the Lean mechanised type-checker is reachable from our workbench, (2) the Rust reference gives the expected decisions on a readable policy set, (3) a Lean type-directed generator produces well-typed Cedar-micro expressions, and (4) the Rust reference and the Go reimplementation agree on 7760 diverse test cases.

## How to run

```
git clone --recurse-submodules https://github.com/athanor-ai/kairos-cedar.git
cd kairos-cedar
docker pull ghcr.io/athanor-ai/kairos-cedar:latest
python3 demo/run_demo.py
```

The image is approximately 9 GB; pulling it from a cold cache takes 1-2 minutes on a reasonable connection. The demo itself runs in 20-40 seconds once the image is local.

## What is currently hand-written vs mechanically derived

The generator in part (3) is hand-authored type-directed code following the structure of the Lean type-system spec. The per-type Palamedes scaffolding in `cedar-micro/CedarMicro/{Ty,Expr}.lean` is in place (companion functors, recursion schemes, fold coercions, `as_or` / `deforest_eq` rewrites, `Total.total_unfold` registered under the `totality` aesop rule set), but the `generator_search` proof-search tactic has not yet been invoked against `isWellTyped`. V2 replaces the hand-authored generator with the mechanically-derived one.

## Fixtures

The hand-authored policies and requests live in `demo/fixtures/`:

- `policy.cedar`: three-policy RBAC set.
- `schema.cedarschema`: type declarations for the RBAC set.
- `entities.json`: five entities (two roles, three users, two documents).
- `requests.jsonl`: six requests with expected `Allow`/`Deny` labels.

All four are small enough to read in 30 seconds.
