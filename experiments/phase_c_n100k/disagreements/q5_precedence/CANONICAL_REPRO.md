# CANONICAL_REPRO: q5_precedence__q5_sc_dec_plus_true

## Classification
`evaluator_disagreement`

## Cedar Policy (AST)
```cedar
permit(principal, action, resource) when { true && decimal("+1.0").lessThan(decimal("2.0")) };
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

error while evaluating policy `policy0`: error while evaluating `decimal` extension function: `+1.0` is not a well-formed decimal value
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
B1 (decimal parser over-accepts)
