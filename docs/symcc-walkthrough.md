# cedar symcc walkthrough

A practical guide to running the Cedar symbolic compiler (`cedar symcc`)
inside the kairos-cedar dev container. The container ships
`cedar-policy-cli 4.10` built with `--features analyze` plus CVC5 1.3.1,
so every `cedar symcc` subcommand is reachable without extra setup.

This walkthrough mirrors the experiments behind the 70-tuple sweep
(see `experiments/phase_c_diff/bug-hunt-2026-04-25/run_70_tuple_sweep.sh`)
and the container bake (PR #26). Run it on your laptop in about five
minutes.

## What `cedar symcc` does

Cedar's symbolic compiler proves properties about a policy set against
*every* well-typed request, instead of testing one request at a time.
The compiler emits SMT-LIB to CVC5; CVC5 returns either UNSAT (the
property holds) or a counterexample (a request that violates it). The
SDK side never sees a CVC5 invocation directly; the `cedar symcc`
subcommand is the only public entry point.

The bundled subcommands (output of `cedar symcc --help`):

| Subcommand | Question it answers |
| :- | :- |
| `never-errors` | Does this policy always evaluate without runtime error? |
| `always-matches` | Is this policy's match condition a tautology? |
| `never-matches` | Is this policy's match condition unsatisfiable? |
| `matches-equivalent` | Do two policies have the same match condition? |
| `matches-implies` | Does policy A's match condition imply policy B's? |
| `matches-disjoint` | Are two policies' match conditions mutually exclusive? |
| `always-allows` | Does this policy set allow every well-formed request? |
| `always-denies` | Does this policy set deny every well-formed request? |
| `equivalent` | Are two policy sets logically equivalent? |
| `implies` | Does policy set A imply policy set B (subsumption)? |
| `disjoint` | Are two policy sets disjoint (no overlapping permissions)? |

Each subcommand requires a schema (the type system the policy is
written against), a principal type, an action, and a resource type.

## Prerequisites

The dev container has everything baked in. Pull or build it:

```bash
docker pull ghcr.io/athanor-ai/kairos-cedar:latest
# or build from source:
docker build -f containers/Containerfile -t kairos-cedar:dev .
```

Verify the toolchain is present:

```bash
docker run --rm kairos-cedar:dev cedar --version
# cedar-policy-cli 4.10.0
docker run --rm kairos-cedar:dev cvc5 --version | head -1
# This is cvc5 version 1.3.1
docker run --rm kairos-cedar:dev cedar symcc --help | head -3
# Symbolic analysis of Cedar policies using SymCC
```

If any of those fail, check that the `--features analyze` flag is on
the cedar build (the container bakes it in via PR #26).

## Worked example: prove a policy never errors

The simplest property to verify is `never-errors`: given a fixed
principal, action, and resource type, does the policy evaluate to a
verdict for every concrete request?

Make a working directory and drop three files:

`schema.cedarschema` (Cedar schema syntax; pass `--schema-format json` if you'd rather use JSON):

```cedar
entity User;
entity File {
  owner: User,
};
action read appliesTo {
  principal: [User],
  resource: [File],
};
```

`policy.cedar`:

```cedar
permit (principal, action == Action::"read", resource)
when { resource.owner == principal };
```

`run.sh`:

```bash
#!/bin/bash
set -euo pipefail
cedar symcc \
  --principal-type 'User' \
  --action 'Action::"read"' \
  --resource-type 'File' \
  --schema schema.cedarschema \
  never-errors \
  --policies policy.cedar
```

Note: the shared flags (`--principal-type`, `--action`, `--resource-type`, `--schema`) come BEFORE the subcommand name; per-subcommand flags (`--policies`, etc.) come after. Reverse the order and Cedar prints `error: unexpected argument`.

Then mount the directory into the container:

```bash
docker run --rm -v "$PWD:/work" -w /work kairos-cedar:dev bash run.sh
```

A clean run prints `✓ Policy never errors: VERIFIED`. If the symbolic
compiler finds a request that triggers a runtime error, it emits the
counterexample as a JSON request shape you can paste back into
`cedar evaluate` for confirmation.

## Verifying two policy sets are equivalent

The most useful subcommand for refactors is `equivalent` - given two
policy directories, prove they grant identical access on every
well-formed request:

```bash
cedar symcc \
  --principal-type 'User' \
  --action 'Action::"read"' \
  --resource-type 'File' \
  --schema schema.cedarschema.json \
  equivalent \
  --policies before/ \
  --comparison-policies after/
```

A policy refactor that's intended to be behavior-preserving but
introduces a subtle privilege change (e.g., a new `unless` clause
that inadvertently removes a permission) gets caught here. The
counterexample is the request that distinguishes the two sets.

## When CVC5 hangs or returns unknown

Some Cedar surface fragments hit encoder-coverage gaps. The two we
catalogued during the §9.3 sweep:

1. **`toTime` on a free `datetime` variable** - the symbolic encoder
   emits an `ite`-on-`bvsrem` formula that CVC5 doesn't simplify
   within reasonable wall-time. Workaround: pin the datetime via a
   `when` clause that bounds the variable. Tracked in
   `Cedar/SymCC/ExtFun.lean`.
2. **Empty set literal in a `when` clause** - the Lean `compileSet`
   guard rejects this at compile time before reaching CVC5. Rewrite
   as `containsAll` against a non-empty literal if you need the
   semantics.

Neither is a soundness failure. Both narrow the surface on which the
symbolic-vs-concrete oracle can be applied (paper §9.3).

If your policy hangs and you suspect coverage gap (rather than CVC5
runtime), pass `--cvc5-path` and watch the SMT-LIB it generates:

```bash
cedar symcc \
  --principal-type 'User' --action 'Action::"read"' --resource-type 'File' \
  --schema schema.cedarschema.json \
  --cvc5-path /usr/local/bin/cvc5 \
  never-errors --policies policy.cedar
```

## Speed expectations

Per the §9.3 70-tuple sweep with the bundled CVC5 1.3.1:

| Policy shape | Median wall-clock | 95th percentile |
| :- | :- | :- |
| Single `permit` with one `when` clause, primitive types | 30 ms | 80 ms |
| Set / record / nested-attribute access in `when` | 100 ms | 350 ms |
| `equivalent` over two 20-policy sets | 1.1 s | 4.2 s |
| Policy with extension types (datetime, duration, IP, decimal) | 200 ms | hangs (toTime gap above) |

Anything noticeably slower is worth checking against the encoder
gaps before assuming a CVC5 issue.

## How `cedar symcc` fits the kairos-cedar pipeline

`cedar symcc` is the production-grade Cedar reference's own symbolic
compiler. kairos-cedar uses it as the *third oracle* in its
differential-testing pipeline (paper §8): a tuple is generated by
the type-directed Lean generator, evaluated by `cedar-policy` (Rust)
and `cedar-go` (Go), and cross-checked symbolically with `cedar
symcc`. A disagreement between the two production evaluators that
also appears symbolically narrows the bug to either both
implementations or the symbolic encoder.

Container image: `ghcr.io/athanor-ai/kairos-cedar:latest`.
Container source: `containers/Containerfile` (introduced in PR #26).

## Reference

- `cedar-policy-cli` repo: https://github.com/cedar-policy/cedar
- CVC5 release notes for 1.3.1: https://github.com/cvc5/cvc5/releases/tag/cvc5-1.3.1
- The SDK security model touches CVC5 only as a black box; no
  trust relationship beyond "we shipped a known-good binary."
