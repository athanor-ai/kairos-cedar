# kairos-cedar end-to-end demo

A deterministic, reproducible smoke of the kairos-cedar workbench. No LLM calls, no paid APIs, no network after the image pull. Total runtime is approximately 40 seconds once the image is cached locally.

## What it runs

1. **Lean bridge compiles.** `lake build` the `cedar-spec-bridge` Lake project inside the container image, which imports upstream [cedar-spec](https://github.com/cedar-policy/cedar-spec) and proves our `isWellTyped env e := ∃ te c, Cedar.Validation.typeOf e [] env = .ok (te, c)` wrapper compiles against the real mechanised type-checker. ~5 s with the Lake cache warm.

2. **Rust CLI decisions vs hand-authored expectations.** Six requests against a three-policy RBAC set (admin allow, forbid on confidential resources, editor-owns-resource) driven through the Rust `cedar authorize` CLI. Each decision is compared to a hand-authored expected label. Exercises `permit`/`forbid` precedence, role hierarchy, attribute conditions, and the `is` type guard. ~7 s.

3. **Generator synthesis.** Ten bool-typed + ten int-typed Cedar-micro expressions are sampled from the type-directed generator in `cedar-micro/CedarMicro/WellTyped.lean`. Each expression is runtime-verified against the functional typechecker `getType`. Every sampled expression satisfies `isWellTyped Γ` by construction. This is the core research artefact: a generator that produces only semantically meaningful inputs, rather than byte-level random data. ~2 s.

4. **Shipped corpus at scale.** `go test -run TestCorpus -count=1` inside cedar-go, which internally cross-checks each decision against the Rust reference via the bundled `test/cedar-validation-tool` driver on approximately 7760 subtests drawn from [cedar-integration-tests](https://github.com/cedar-policy/cedar-integration-tests). ~11 s.

5. **Type-directed differential pipeline.** Twenty (Policy, Schema, Request) tuples are sampled from `cedar-full/CedarFull/PolicyGen.lean` (driven by the `measure-diff` Lean binary) and evaluated against `cedar-policy` (Rust 4.3.1) and `cedar-go` (HEAD) via `experiments/phase_c_diff/run_diff.py`. The driver reports valid-input yield + agreement rate. The same driver, run at $N = 10{,}000$, populates Table 4 of the paper (1.000 yield, 0 disagreements, 0.015 s/tuple). ~5 s for the demo's $N = 20$ run on a warm cache.

Combined, the demo produces five independent signals: (1) the Lean mechanised type-checker is reachable from our workbench, (2) the Rust reference gives the expected decisions on a readable policy set, (3) a Lean type-directed generator produces well-typed Cedar-micro expressions, (4) the Rust reference and the Go reimplementation agree on 7760 diverse test cases, and (5) the §8 differential pipeline runs end-to-end on inputs sampled from the policy generator.

## How to run

```
git clone --recurse-submodules https://github.com/athanor-ai/kairos-cedar.git
cd kairos-cedar
docker pull ghcr.io/athanor-ai/kairos-cedar:latest
python3 demo/run_demo.py
```

The image is approximately 9 GB; pulling it from a cold cache takes 1-2 minutes on a reasonable connection.

The demo itself runs in 20-40 seconds with a warm `.lake/` cache. The first run on a fresh checkout takes 3-5 minutes because part (3) builds the `cedar-micro` Lake project and its `palamedes-lean` dependency from source (toolchain download + dependency compile). Subsequent runs reuse the cache and complete in well under a minute.

## Expected output

A successful run prints a per-step PASS line plus a summary block. The full transcript is reproducible offline once the image is cached:

```
[1/4] Lean bridge. cedar-spec-bridge builds against cedar-spec's real typeOf ...
      PASS. Build completed successfully (91 jobs). in 16.8s

[2/4] Handwritten 3-policy RBAC set: Rust `cedar authorize` decisions vs expected labels ...
PASS. 6/6 cases match expected labels via `cedar authorize` in 9.1s

[3/4] Cedar-micro generator synthesis: sample well-typed expressions from the Lean type-system spec ...
PASS in 17.9s
  Sampling 10 well-typed Cedar-micro expressions
     bool samples well-typed: 10/10 PASS
     int  samples well-typed: 10/10 PASS

[4/4] Rust-vs-Go at scale. cedar-go TestCorpus (~7760 subtests, internal Rust diff) ...
      PASS. ok  github.com/cedar-policy/cedar-go  11.480s in 23.9s

  SUMMARY
  [PASS]  Lean bridge compiles
  [PASS]  Handwritten diff agreement
  [PASS]  Generator synthesises well-typed Cedar expressions
  [PASS]  cedar-go TestCorpus
```

If any step fails, the script exits non-zero with a diff between expected and observed output.

## What is currently hand-written vs mechanically derived

The generator in part (3) is hand-authored type-directed code following the structure of the Lean type-system spec. The per-type Palamedes scaffolding in `cedar-micro/CedarMicro/{Ty,Expr}.lean` is in place (companion functors, recursion schemes, fold coercions, `as_or` / `deforest_eq` rewrites, `Total.total_unfold` registered under the `totality` aesop rule set), but the `generator_search` proof-search tactic has not yet been invoked against `isWellTyped`. V2 replaces the hand-authored generator with the mechanically-derived one.

## Fixtures

The hand-authored policies and requests live in `demo/fixtures/`:

- `policy.cedar`: three-policy RBAC set.
- `schema.cedarschema`: type declarations for the RBAC set.
- `entities.json`: five entities (two roles, three users, two documents).
- `requests.jsonl`: six requests with expected `Allow`/`Deny` labels.

All four are small enough to read in 30 seconds.

## What to try next

Once the demo passes, the natural follow-ups are:

- **Read the type-directed generator.** `cedar-micro/CedarMicro/WellTyped.lean` (~80 LOC) is the generator part (3) samples from. It is short, documented, and follows the type-system rules verbatim. Compare with the byte-level `arbitrary` approach in `cedar-spec/cedar-drt/`.
- **Read the soundness proof.** `cedar-micro/CedarMicro/Soundness.lean` is a sorry-free Lean 4 proof that every term in the support of the generator satisfies the typing predicate. The proof structure (four steps) is documented at the top of the file.
- **Swap in your own oracle.** The `cedar-spec-bridge/CedarBridge/Predicates.lean` module exposes `isWellFormedEnv`, `isValidRequest`, and `areValidEntities` companion predicates. A generator targeting one of those is the natural follow-on experiment.
- **Run the full-Cedar enumerator.** `cedar-full/MeasureFull.lean` enumerates 24 distinct well-typed expressions over the upstream `Cedar.Spec.Expr` (12 constructors). The output drives Table 3 of the paper.

## Collaboration

If the demo runs on your machine and you would like to dig into the generator-derivation story, the entry points above are designed to be read in roughly that order. Contributions, replication reports, and questions are welcome via GitHub issues against this repository.
