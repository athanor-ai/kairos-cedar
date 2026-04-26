# NEW-7: cedar-go drops `entities: []` from action-in scope on JSON round-trip

**Severity:** Low; the empty-set action-in scope has unusual semantics; output is semantically equivalent
**Class:** Silent diff; `entities` key disappears

## Summary

When a Cedar JSON policy uses `{"op": "in", "entities": []}` for an action scope
(action matches nothing), cedar-go's round-trip drops the `entities` key entirely,
producing `{"op": "in"}`.

## Example probe (E-001-action-in-empty-set)

Input:
```json
{"action": {"op": "in", "entities": []}}
```

Cedar text produced:
```
permit(principal, action in [], resource);
```

Output JSON:
```json
{"action": {"op": "in"}}
```

The `entities` key is gone. The round-tripped JSON has `op: "in"` with neither
`entity` nor `entities`, which would fail scope parsing on re-input.

## Root cause

In `json.go`, `scopeJSON.ToActionNode()`, when `op == "in"` and `entity == nil`,
it reads `s.Entities` (which is empty `[]`) and calls `ast.Scope{}.InSet(es)` with an
empty slice. The `InSet` with empty entities creates a `ScopeTypeInSet` with
`Entities: []`. When marshalled back to JSON, the cedar-go JSON marshaller may emit
only `op: "in"` without the `entities` array if the slice is empty or nil.

Additionally, the Cedar text `action in []` renders correctly (empty set), but when
the Cedar text parser reads it back, it might produce a different scope representation.

## Honest assessment

An action scope of `in []` matches no action and is vacuously restrictive. The semantic
effect of the output `{"op": "in"}` without `entities` is that re-parsing would fail
(missing required field), making this a genuine round-trip loss.

## cedar-policy (Rust) behavior

The Rust cedar translate-policy rejects `{"op": "in", "entities": []}` in the action
scope position as an error (requires `conditions` field in input). This is a different
failure mode.

## Affected probes

- `E-001-action-in-empty-set`
