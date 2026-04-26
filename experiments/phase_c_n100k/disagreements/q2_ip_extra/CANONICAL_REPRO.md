# CANONICAL_REPRO: q2_ip_extra__q2_zone_num

## Classification
`evaluator_disagreement`

## Cedar Policy (AST)
```cedar
permit(principal, action, resource) when { ip("fe80::4%1").isIpv6() };
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

error while evaluating policy `policy0`: error while evaluating `ipaddr` extension function: invalid IP address: fe80::4%1
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
B2 (IP parser over-accepts)
