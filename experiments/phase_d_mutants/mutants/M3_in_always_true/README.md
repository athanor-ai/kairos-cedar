# M3 — `in` operator unconditionally true

## Injected bug
In `cedar-go/internal/eval/evalers.go`, `inEval.Eval` returns
`types.Boolean(true)` regardless of operands instead of dispatching to
`doInEval` for the actual hierarchy check. Operands are still evaluated
(to preserve error semantics) and discarded.

## Why this should be detectable
The `in` operator is used in the principal/action/resource scope
(`principal in User::"alice"`, etc.) and inside `when`/`unless`
conditions. When unconditionally true, scope tests that should fail
now succeed; many Deny verdicts flip to Allow.

The CedarFull generator emits both `principal == U::"x"`-style and
`principal in U::"x"`-style scope clauses, plus `when { ... in ... }`
predicates over the entity hierarchy, so M3 should change the decision
for a non-trivial fraction of policies.

## Expected disagreement rate
Tens of percent — driven by the share of generated policies that use
`in` in a load-bearing position.
