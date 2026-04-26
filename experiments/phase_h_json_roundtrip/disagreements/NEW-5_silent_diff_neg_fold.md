# NEW-5: cedar-go folds neg(Value(n)) into Value(-n) on JSON round-trip

**Severity:** Low; semantically equivalent, but JSON representation changes
**Class:** Silent diff on conformant input

## Summary

When a Cedar JSON policy uses `{"neg": {"arg": {"Value": 5}}}` to represent `-5`,
cedar-go's round-trip produces `{"Value": -5}`. The AST node type changes from
a `Negate` expression to an integer literal.

## Example probe (A-015-negate)

Input:
```json
{"neg": {"arg": {"Value": 5}}}
```

Cedar text produced: `-(5)` then round-trip: `-5`

After the second parse, the cedar text `-5` is parsed as an integer literal `-5`,
not as `Negate(5)`. When marshalled, it becomes `{"Value": -5}`.

## Root cause

Cedar's text parser treats `-5` as a literal integer (via `unary()` special-casing in
`cedar_unmarshal.go:720-727`), not as `Negate(Value(5))`. The JSON input `{"neg": {"arg": {"Value": 5}}}` is semantically equivalent but uses the explicit negate form. After the Cedar text round-trip, the negate form is collapsed into the literal.

This is documented behavior in the Cedar grammar; `-(5)` and `-5` are both valid
representations, and the parser normalizes to the literal form.

## Honest assessment

This is **semantically equivalent**; both represent the integer -5. The JSON
representation changes (`neg` expression → `Value` integer), but the semantic meaning
is identical. This is a representation normalization, not a bug.

However, it means JSON round-trip is **not a strict identity** for the `neg` operator
when applied to integer literals. If a consumer depends on the exact JSON structure
(e.g., distinguishing `neg(Value(5))` from `Value(-5)`), this would be surprising.

## cedar-policy (Rust) behavior

The Rust cedar translate-policy translates `{"neg": {"arg": {"Value": 5}}}` to
`-(5)` in Cedar text, then back to `{"neg": {"arg": {"Value": 5}}}`; preserving the
explicit negate form. This is a minor representation difference between impls.

## Affected probes

- `A-015-negate`
