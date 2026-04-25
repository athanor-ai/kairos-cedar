# M5 — `==` always true

## Injected bug
In `cedar-go/internal/eval/evalers.go`, `equalEval.Eval` returns
`types.Boolean(true)` instead of `lv.Equal(rv)`.

A stronger version of "equality loosened to same-type": for the
single-type comparisons CedarFull generates (entity-uid == entity-uid,
literal == literal), the practical effect on observed behaviour is the
same — every `==` returns true.

## Why this should be detectable
`==` shows up in CedarFull policies as the principal/action/resource
scope expansion (`principal == User::"alice"`) and inside `when`
clauses. When `==` always returns true, scope filtering collapses and
many policies that should be inapplicable to a request now apply.

## Expected disagreement rate
Tens of percent — high if the generator emits a lot of `==` in scopes,
moderate otherwise.
