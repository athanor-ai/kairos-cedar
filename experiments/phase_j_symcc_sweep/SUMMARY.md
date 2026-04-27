# Phase J: cedar symcc + CVC5 encoder coverage sweep

Branch: platform/symcc-encoder-bugs
Date: 2026-04-27
Cedar: cedar-policy-cli 4.10.0 (Rust), CVC5 1.3.1
Container: ghcr.io/athanor-ai/kairos-cedar:latest

## Sweep parameters

- N = 1000 tuples from the 42-shape Lean generator
- 11 subcommands per tuple; 11,000 total invocations; 123.8 s wall time
- Per-invocation timeout: 30 s; 0 timeouts observed
- Plus 50+ targeted probes for gap-specific inputs

## Aggregate outcome table

| Subcommand         | VERIFIED | COUNTEREXAMPLE | ENCODE_FAIL |
|--------------------|----------|----------------|-------------|
| never-errors       |      983 |              0 |          17 |
| always-matches     |      464 |            519 |          17 |
| never-matches      |      322 |            661 |          17 |
| always-allows      |      430 |            553 |          17 |
| always-denies      |      389 |            594 |          17 |
| matches-equivalent |      983 |              0 |          17 |
| matches-implies    |      983 |              0 |          17 |
| matches-disjoint   |      322 |            661 |          17 |
| equivalent         |      983 |              0 |          17 |
| implies            |      983 |              0 |          17 |
| disjoint           |      389 |            594 |          17 |

All 17 ENCODE_FAIL rows trace to shape 39 (permit-when-principal-in-empty-set):
EmptySetForbidden class (documented in symcc-walkthrough.md).

## Bug-class table

| ID | Class           | Finding                                               |
|----|-----------------|-------------------------------------------------------|
| 01 | encoder-gap     | Empty-set literal rejected pre-CVC5 (documented)      |
| 02 | encoder-gap     | Template policies silently dropped from policy-set analysis |
| 03 | encoder-gap     | Single-policy constraint on never-errors/always-matches/never-matches |
| 04 | encoder-gap     | appliesTo constraints not modeled in SMT environment  |
| 05 | soundness-bug   | toDate overflow yields bogus always-matches counterexample |
| 06 | encoder-gap     | Asymmetric schema pre-check: missing action vs out-of-appliesTo |
| 07 | encoder-gap     | Template-slot policies give opaque "found 0" error    |

Totals: 6 encoder-gaps, 1 soundness-bug, 0 timeouts.

## New gaps beyond symcc-walkthrough.md

### Gap A (Finding 02): Template policies silently dropped

Policy-set subcommands warn and drop template policies. A template-only permit
set receives always-denies: VERIFIED despite the linked template producing ALLOW.
Spec: Cedar/SymCC/Verifier.lean:67-71.

### Gap B (Finding 03): Single-policy count constraint

never-errors, always-matches, never-matches, and the matches-* family require
exactly one policy each. No API for "does any policy in this set never error?"
Spec: Cedar/SymCC/Verifier.lean:78 (verifyNeverErrors takes a single Policy).

### Gap C (Finding 04): appliesTo not in SMT model

Symbolic environment does not enforce appliesTo principal/resource restrictions.
Queries with out-of-appliesTo --principal-type succeed where concrete Cedar rejects.
Spec: Cedar/SymCC/Compiler.lean:52-57 (compileVar checks entity type, not appliesTo).

### Gap D (Finding 05): toDate overflow yields bogus counterexample

For offset(datetime("1970-01-01"), duration("-9223372036854775808ms")), toDate
overflows in the concrete evaluator but toTime uses compileCall1 (not
compileCallWithError1), failing to propagate the error, so CVC5 produces a
false DOES NOT HOLD witness.
Spec: Cedar/SymCC/ExtFun.lean:154-173 + Cedar/SymCC/Compiler.lean:241-242.

### Gap E (Finding 06): Asymmetric schema pre-check

Missing action UIDs raise ENCODE_FAIL; out-of-appliesTo principal types are
silently accepted. Inconsistent and undocumented.

### Gap F (Finding 07): Opaque "found 0" for template-slot policies

Template policies in single-policy subcommands produce "Expected exactly one
policy, found 0" with no mention that a template was discarded.

## Canonical reproducers

All reproducer details in experiments/phase_j_symcc_sweep/findings/.
Runner: experiments/phase_j_symcc_sweep/run_symcc.py (N=1000 sweep).
