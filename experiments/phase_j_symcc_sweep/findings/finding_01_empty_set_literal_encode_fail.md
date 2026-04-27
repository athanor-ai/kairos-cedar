# Finding 01: Empty-set literal rejected before CVC5 (encoder coverage gap)

**Class:** encoder-gap (pre-CVC5 rejection)
**Subcommands affected:** all 11 (never-errors, always-matches, never-matches,
matches-equivalent, matches-implies, matches-disjoint, always-allows,
always-denies, equivalent, implies, disjoint)
**Severity:** coverage gap; Cedar policies using `[]` cannot be analyzed symbolically

## Reproducer

Schema: `schema.cedarschema` (fixed User/Document/Photo schema).

Policy:
```cedar
permit(principal, action, resource) when { (principal in []) };
```

Command:
```bash
cedar symcc \
  --principal-type User \
  --action 'Action::"view"' \
  --resource-type Document \
  --schema schema.cedarschema \
  never-errors --policies policy.cedar
```

Output:
```
Analysis failed: x Failed to compile policy: input policy (set) is not well
typed with respect to the schema [EmptySetForbidden(...)]
RC: 1
```

## Root cause

`Cedar/SymCC/Compiler.lean:187` (compileSet):
```lean
| [] => .error .unsupportedError  -- reject empty set literals
```

The Lean symbolic compiler explicitly rejects empty set literals at compile time.
The type-checker's `EmptySetForbidden` diagnostic fires before the SMT encoding
stage. This also applies to empty sets nested in `containsAll`, `containsAny`,
and `contains` call arguments.

## Spec source attribution

`Cedar/Spec/Evaluator.lean` permits membership tests against empty sets (always
evaluates to false). The concrete evaluator handles `in []` without error.
`Cedar/SymCC/Compiler.lean:187` makes the symbolic path stricter than the
concrete path.

## Count in N=1000 sweep

17 invocations affected (shape 39: `permit-when-principal-in-empty-set`),
uniform across all 11 subcommands.

## Note

This finding is one of two documented in `docs/symcc-walkthrough.md` (the other
being the `toTime` CVC5 hang). It is confirmed by the N=1000 sweep and included
for completeness.
