# kairos-cedar end-to-end demo

A deterministic, reproducible smoke of the kairos-cedar workbench. No LLM calls, no paid APIs, no network after the image pull. Total runtime is approximately 30 seconds once the image is cached locally.

## What it runs

1. **Lean bridge compiles.** `lake build` the `cedar-spec-bridge` Lake project inside the container image, which imports upstream [cedar-spec](https://github.com/cedar-policy/cedar-spec) and proves our `isWellTyped env e := ∃ te c, Cedar.Validation.typeOf e [] env = .ok (te, c)` wrapper compiles against the real mechanised type-checker. ~5 s with the Lake cache warm.

2. **Rust CLI decisions vs hand-authored expectations.** Six requests against a three-policy RBAC set (admin allow, forbid on confidential resources, editor-owns-resource) driven through the Rust `cedar authorize` CLI. Each decision is compared to a hand-authored expected label. Exercises `permit`/`forbid` precedence, role hierarchy, attribute conditions, and the `is` type guard. ~7 s.

3. **Shipped corpus at scale.** `go test -run TestCorpus -count=1` inside cedar-go, which internally cross-checks each decision against the Rust reference via the bundled `test/cedar-validation-tool` harness on approximately 7760 subtests drawn from [cedar-integration-tests](https://github.com/cedar-policy/cedar-integration-tests). ~11 s.

Combined, the demo produces three independent signals: (1) the Lean mechanised type-checker is reachable from our workbench, (2) the Rust reference gives the expected decisions on a readable policy set, (3) the Rust reference and the Go reimplementation agree on 7760 diverse test cases.

## How to run

```
git clone --recurse-submodules https://github.com/athanor-ai/kairos-cedar.git
cd kairos-cedar
docker pull ghcr.io/athanor-ai/kairos-cedar:latest
python3 demo/run_demo.py
```

The image is approximately 9 GB; pulling it from a cold cache takes 1-2 minutes on a reasonable connection. The demo itself runs in 20-30 seconds once the image is local.

## What it does not demonstrate

- The generator-derivation pipeline described in `../README.md` and `../docs/ROADMAP.md`. That is the V1/V2 deliverable; V0 (this demo) shows the infrastructure and the methodology, not the generator.
- Evaluation or symbolic-compilation differential tests beyond the shipped corpus. Those are V3.
- Any LLM-assisted work. The pipeline does not exist yet in the public repository.

## Fixtures

The hand-authored policies and requests live in `demo/fixtures/`:

- `policy.cedar`: three-policy RBAC set.
- `schema.cedarschema`: type declarations for the RBAC set.
- `entities.json`: five entities (two roles, three users, two documents).
- `requests.jsonl`: six requests with expected `Allow`/`Deny` labels.

All four are small enough to read in 30 seconds.
