# CANONICAL_REPRO: q11_decimal_ip_cross__q11_zone_xx1Zlo_inrange_xx1s128

## Classification
`evaluator_disagreement`

## Cedar Policy (AST)
```cedar
permit(principal, action, resource) when { ip("::1%lo").isInRange(ip("::1/128")) };
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

error while evaluating policy `policy0`: error while evaluating `ipaddr` extension function: invalid IP address: ::1%lo
```

## cedar-go (v1.6.0) verdict
**Allow**

```

```

## Spec attribution
Cedar specification does not permit this input form. cedar-go parser accepts
what cedar-policy (reference implementation) rejects, causing divergent
authorization outcomes.

## Bug class
B2 (IP parser over-accepts zone-id)
