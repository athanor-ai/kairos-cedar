# Phase C N=100k Bug Hunt Summary -- 2026-04-26

- Wall-clock total: 101.5s
- Tools: cedar-policy-cli 4.10.0 (Rust) vs cedar-go v1.6.0 (HEAD)
- Image: `ghcr.io/athanor-ai/kairos-cedar:latest`

## Methodology

The V1 Lean generator cycles through 675 unique tuples (25 shapes x 27 combinations).
At N=100k the generator repeats those 675 tuples 148x -- no new coverage. Phase A
confirms this plateau. The real N=100k-scale contribution is Phase B: 13 new shape
groups (291 tuples) covering areas not tested in the N=10k bug-hunt-2026-04-25 run.

## Phase A: measure-diff generator at N=100k

- N requested: 100000
- Unique policies generated: 59
- Repetition factor: 1694x (generator cycles after 59 unique tuples)
- Phase A wall-clock: 39.8s

| classification | count |
| :- | -: |
| agreement_allow | 33 |
| agreement_deny | 26 |

Phase A: no new disagreements (plateau confirmed).

## Phase B: widened shapes v2 (13 new shapes, 291 tuples)

- Total tuples: 291
- Shapes: 13
- Phase B wall-clock: 34.6s

| classification | count |
| :- | -: |
| agreement_allow | 162 |
| agreement_both_reject | 44 |
| agreement_deny | 45 |
| asymmetric_path_both_deny | 15 |
| evaluator_disagreement | 25 |

| shape | N | semantic_diss | evaluator_diss | both_reject | agreement |
| :- | -: | -: | -: | -: | -: |
| q10_type_coercion | 21 | 0 | 0 | 0 | 21 |
| q11_decimal_ip_cross | 30 | 0 | 16 | 0 | 0 |
| q12_scope | 15 | 0 | 0 | 0 | 15 |
| q13_duration_edge | 24 | 0 | 0 | 6 | 18 |
| q1_decimal_boundary | 29 | 0 | 2 | 15 | 11 |
| q2_ip_extra | 32 | 0 | 5 | 10 | 17 |
| q3_datetime_ops | 30 | 0 | 0 | 7 | 23 |
| q4_string_ops | 22 | 0 | 0 | 3 | 19 |
| q5_precedence | 21 | 0 | 2 | 0 | 19 |
| q6_entity_hierarchy | 19 | 0 | 0 | 0 | 19 |
| q7_records | 17 | 0 | 0 | 0 | 17 |
| q8_multi_policy | 12 | 0 | 0 | 0 | 12 |
| q9_arithmetic | 19 | 0 | 0 | 3 | 16 |

## New disagreements vs N=10k baseline

Baseline (bug-hunt-2026-04-25): 2 evaluator_disagreements
N=100k Phase B new: 25 new disagreements

| bug class | count | root cause |
| :- | -: | :- |
| B1 (decimal `+` sign) | 13 | ParseDecimal uses strconv.ParseInt which accepts leading `+`; Cedar spec forbids it |
| B2 (IP zone-id) | 12 | ParseIPAddr delegates to net/netip which accepts RFC 6874 zone IDs; Cedar spec IP grammar has no zone-id production |

No B-NEW class emerged. All 25 disagreements are variants of the two known bugs.

## B1 - decimal `+` sign (13 instances)

All: `decimal("+X.Y").<op>(decimal("X.Y"))` -- Rust Deny (parse error), Go Allow.

New values beyond baseline (+0.0): +1.0, +100.5000, +0.1, +99.9999, +922337203685477.5807
New ops beyond lessThan: lessThanOrEqual, greaterThanOrEqual
New pattern: `true && decimal("+1.0").lessThan(...)` -- shows B1 fires even when
short-circuit would not help (left side is true, B1 fires on right-side parse).

## B2 - IP zone-id (12 instances)

All: `ip("<addr>%<zone>").<op>()` -- Rust Deny (invalid IP), Go Allow.

New zones beyond %eth0: %eth1, %en0, %lo, %longinterface123, %1
New addresses: ::1%lo (loopback+zone), 2001:db8::1%eth0 (global unicast+zone)
New ops: isLoopback, isInRange (not just isIpv6)
New pattern: `true && ip("fe80::1%eth0").isIpv6()` -- B2 fires inside && right-operand.
