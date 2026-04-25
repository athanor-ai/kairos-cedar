# M2 — `&&` short-circuit on the wrong branch

## Injected bug
In `cedar-go/internal/eval/evalers.go`, the `andEval.Eval` short-circuit
condition is inverted: `if !b { return v, nil }` (correct: short on
false) becomes `if b { return v, nil }` (incorrect: short on true).

Effect: if `lhs` is true, the expression returns true without
consulting `rhs`. If `lhs` is false, evaluation continues to `rhs` and
returns its value. So `A && B` becomes `A || B`-ish on the
short-circuit path; semantically broken on any policy that needs both
conjuncts.

## Why this should be detectable
Many CedarFull policies generate `when { c1 && c2 }` clauses; under M2
a policy that should be denied because `c2` is false will incorrectly
permit because `c1` was true.

## Expected disagreement rate
Tens of percent — depends on the share of generated policies whose
final decision changes when `&&` is broken. Should be well above the
0% framework noise floor.
