# CANONICAL_REPRO: q11_decimal_ip_cross__q11_zone_fe80xx1Zeth0_inrange_fe80xxs10

## Classification
`evaluator_disagreement`

## Cedar Policy (AST)
```cedar
permit(principal, action, resource) when { ip("fe80::1%eth0").isInRange(ip("fe80::/10")) };
```

## Request
- principal: `User::alice`
- action: `Action::view`
- resource: `Document::doc1`
- context: `{}`

## cedar-policy (Rust 4.10.0) verdict
**Deny**

```
DENY

error while evaluating policy `policy0`: error while evaluating `ipaddr` extension function: invalid IP address: fe80::1%eth0
```

## cedar-go (v1.6.0) verdict
**Allow**

```

```

## Spec attribution
Cedar specification grammars do not include this input form. cedar-go parser
accepts what cedar-policy (reference implementation) rejects, causing divergent
authorization outcomes. Both implementations agree: a failed `when` clause
extension parse causes Rust to Deny (no applicable permit). Cedar-go silently
accepts the malformed literal, evaluates the condition as true, and grants Allow.

## Bug class
B2 (IP parser over-accepts RFC 6874 zone identifiers)
