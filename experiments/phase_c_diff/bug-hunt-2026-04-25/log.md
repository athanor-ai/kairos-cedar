# Bug-Hunt Log  - 2026-04-25

Goal: find a real cedar-policy ↔ cedar-go evaluator disagreement at all
costs to flip the FMCAD paper from borderline to FMCAD-grade.

Tools (locked):
- cedar-policy-cli **4.10.0** (Rust)  ← container ghcr.io/athanor-ai/kairos-cedar:latest
- cedar-go **v1.6.0** (HEAD a9a4b1b on this branch  - submodule pinned)
- Lean 4.29.1
- Container image hash: `d9c9ceb6be83`

Caveat noted in run_diff.py docstring: it claims cedar-policy 4.3.1  - actual
container ships 4.10.0. The 0/10000 V1 result was actually against 4.10.0.

Generator support analysis:
- `CedarFull.PolicyGen.genTuple` has support 25 shapes × 27 (p×a×r) = 675.
- `MeasureDiff.lean` cycles via `i % supportSize`, so N=10000 = 14× repeat.
- N=10⁶ on the V1 generator is pointless  - it cycles the same 675 tuples.
- Conclusion: scaling is not the move. Widening shapes is.

## Plan

Add 11 widened shapes (206 tuples) in
`bug-hunt-2026-04-25/widened_shapes.py`:

- p1_decimal_parse           (30 tuples)  ← Aidan's #1
- p1_decimal_compare         (32)
- p2_ip_parse                (28)
- p2_ip_ops                  (32)
- p2_ip_in_range             (10)
- p3_datetime_parse          (21)
- p4_unicode_like            (16)
- p5_set_ops                 (11)
- p6_short_circuit           (12)
- p7_iam_layered             (8)
- p8_rbac_docshare           (6)

Each tuple: (principal, action, resource, policy text). Run through the
existing Rust+Go batch runners in `run_widened.py`. Classify per-pair as:
agreement_allow, agreement_deny, agreement_both_reject,
evaluator_disagreement (one accepts, one rejects),
semantic_disagreement (both succeed but Allow vs Deny  - paper grade).

Read-only on V1 generator + V1 corpus. New work in `bug-hunt-2026-04-25/`.

## Timeline

### 19:30 UTC  - harness scaffolded
- Wrote `widened_shapes.py` (11 shapes, 206 tuples) + `run_widened.py`.
- Smoke test on p1_decimal_parse exposed two harness bugs:
  - schema didn't permit User→Group ancestry (entities rejected).
  - classifier mistakenly read cedar CLI rc=2 as error (rc=2 = any Deny).
- Both fixed. Schema updated to `entity User in [Group]` etc.

### 19:48 UTC  - full sweep complete (206 tuples, 9 min wall-clock)

| classification | count |
|---|---|
| agreement_allow | 87 |
| agreement_deny | 71 |
| agreement_both_reject | 41 |
| asymmetric_path_both_deny | 5 |
| **evaluator_disagreement (decision-flip)** | **2** |

Two paper-grade decision-flips, both rooted in cedar-go parsers being
wider than the Cedar specification:

1. **decimal `+0.0`**  - `decimal("+0.0").lessThan(decimal("0.5"))` →
   Rust Deny, Go Allow. Root cause: `types/decimal.go::ParseDecimal`
   passes the integer part to `strconv.ParseInt` which accepts leading
   `+`. Three more `+`-prefix variants flip in direct probing
   (canonical write-up at
   `disagreements/p1_decimal_parse/CANONICAL_REPRO.md`).

2. **IPv6 zone-id `fe80::1%eth0`**  - `ip("fe80::1%eth0").isIpv6()` →
   Rust Deny, Go Allow. Root cause:
   `types/ipaddr.go::ParseIPAddr` delegates to `net/netip` which
   accepts RFC 6874 zone identifiers. Five more zone-id variants flip
   in direct probing (canonical write-up at
   `disagreements/p2_ip_ops/CANONICAL_REPRO.md`).

Both Lean evaluator attribution: agrees with cedar-policy (Rust). The
Cedar specification grammars do not include `+`-sign on decimal or
zone-identifier on ipaddr. cedar-go bugs.

No 8-h overnight run needed. Stopping here. Founder hand-off.
