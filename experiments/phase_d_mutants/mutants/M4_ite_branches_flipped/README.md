# M4 — `if/then/else` branches swapped

## Injected bug
In `cedar-go/internal/eval/evalers.go`, `ifThenElseEval.Eval` swaps the
two arms: `cond=true` returns the else branch; `cond=false` returns
the then branch.

## Why this should be detectable
CedarFull's `genPolicy` includes shapes that emit `if c then a else b`
inside `when` conditions. Whenever `c`, `a`, and `b` differ in their
boolean evaluation, the policy outcome flips.

## Expected disagreement rate
Smaller than M1/M3 (only the subset of policies actually using `if`),
but still well above noise — bounded below by the share of `ite`-using
policy shapes generated.
