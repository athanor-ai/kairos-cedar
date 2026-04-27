# 02-symcc-never-errors

Use Cedar's symbolic compiler (`cedar symcc`) to prove a policy never errors at runtime, regardless of the request shape.

## What `cedar symcc never-errors` does

Given a fixed (principal type, action, resource type) shape and a policy, `cedar symcc never-errors` asks CVC5 whether there exists ANY well-formed request that causes the policy to evaluate to a runtime error (for example, dereferencing an attribute that may be absent). If CVC5 returns UNSAT the policy is verified to never error; if SAT it returns the counterexample request.

This is stronger than testing one request at a time: the proof covers the entire well-typed request space.

## Files

* `schema.cedarschema`: a `User` and `File` schema.
* `policy.cedar`: a single `permit` over file-read where the principal owns the resource.
* `policy_unsafe.cedar`: a tweak that dereferences an optional attribute without guarding, intended to fail the property.
* `run.sh`: invokes `cedar symcc never-errors` on each policy and reports the verdict.

## Run

Inside the kairos-cedar dev container:

```bash
cd examples/02-symcc-never-errors
./run.sh
```

> **Note**: this example requires the `cedar-policy-cli` binary in the container to be built with `--features analyze`. The Containerfile (`containers/Containerfile`) already builds it that way; the published `ghcr.io/athanor-ai/kairos-cedar:latest` image needs a rebuild after PR #26 (the analyze flag) for `cedar symcc` to be reachable. Until the image refresh ships, this example will print "Cannot run `symcc`: this Cedar CLI was built without the 'analyze' feature enabled" and exit non-zero. See `docs/symcc-walkthrough.md` for the same workflow plus a build-from-source path.

Expected output:

```
policy.cedar:        VERIFIED  (no request causes a runtime error)
policy_unsafe.cedar: COUNTEREXAMPLE  (CVC5 found a request that errors)
```

The `policy_unsafe.cedar` counterexample contains a `User` with no name attribute; the unguarded `principal.name == "alice"` then errors. `cedar symcc` returns the entity shape that triggers the failure.

## Why this matters

A unit-test approach would need to enumerate request shapes. `cedar symcc` covers the whole well-typed request space in one CVC5 call.

For the encoder coverage gaps (a small handful of Cedar fragments that hit CVC5 simplification limits), see `docs/symcc-walkthrough.md` in the repo root.

## License

Apache-2.0. See top-level `LICENSE`.
