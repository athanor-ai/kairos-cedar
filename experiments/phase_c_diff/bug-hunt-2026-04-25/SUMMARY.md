# Widened Bug-Hunt Summary: 2026-04-25

- Total tuples: 206
- Tools: cedar-policy-cli 4.10.0 (Rust) vs cedar-go v1.6.0 (HEAD)
- Image: `ghcr.io/athanor-ai/kairos-cedar:latest`

## Aggregate by classification

| classification | count |
| :- | :- |
| agreement_allow | 87 |
| agreement_both_reject | 41 |
| agreement_deny | 71 |
| asymmetric_path_both_deny | 5 |
| evaluator_disagreement | 2 |

## Per-shape breakdown

| shape | N | semantic_diss | evaluator_diss | both_reject | agreement |
| :- | :- | :- | :- | :- | :- |
| p1_decimal_compare | 32 | 0 | 0 | 0 | 32 |
| p1_decimal_parse | 30 | 0 | 1 | 15 | 13 |
| p2_ip_in_range | 10 | 0 | 0 | 1 | 9 |
| p2_ip_ops | 32 | 0 | 1 | 4 | 24 |
| p2_ip_parse | 28 | 0 | 0 | 8 | 19 |
| p3_datetime_parse | 21 | 0 | 0 | 11 | 10 |
| p4_unicode_like | 16 | 0 | 0 | 0 | 16 |
| p5_set_ops | 11 | 0 | 0 | 0 | 11 |
| p6_short_circuit | 12 | 0 | 0 | 2 | 10 |
| p7_iam_layered | 8 | 0 | 0 | 0 | 8 |
| p8_rbac_docshare | 6 | 0 | 0 | 0 | 6 |

## Disagreements (2)

### `p1_decimal_parse__p1_parse_d_pos_sign_zero`: evaluator_disagreement

```cedar
permit(principal, action, resource) when { principal == User::"alice" && decimal("+0.0").lessThan(decimal("0.5")) };
```

- principal: `User::alice`
- action: `Action::view`
- resource: `Document::doc1`
- rust: `Deny`: `DENY

error while evaluating policy `policy0`: error while evaluating `decimal` extension function: `+0.0` is not a well-formed decimal value`
- go: `Allow`: ``

### `p2_ip_ops__p2_op_fe80xx1_p_eth0_isIpv6`: evaluator_disagreement

```cedar
permit(principal, action, resource) when { ip("fe80::1%eth0").isIpv6() };
```

- principal: `User::alice`
- action: `Action::view`
- resource: `Document::doc1`
- rust: `Deny`: `DENY

error while evaluating policy `policy0`: error while evaluating `ipaddr` extension function: invalid IP address: fe80::1%eth0`
- go: `Allow`: ``

