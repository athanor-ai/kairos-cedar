# M1 — Flip allow/deny in Authorize

## Injected bug
In `cedar-go/authorize.go`, swap every `Allow`/`Deny` return in the
final decision phase of `Authorize`:
- `forbids > 0` returns `Allow` (was `Deny`).
- `permits > 0` returns `Deny` (was `Allow`).
- Default fall-through returns `Allow` (was `Deny`).

## Why this should be detectable
This is the most direct correctness-flipping mutation possible: every
non-error decision is inverted. Expect ~100% disagreement on tuples
that don't error out, since cedar-policy returns the spec answer and
cedar-go now returns its negation.

## Expected disagreement rate
Near 100% on all valid tuples.
