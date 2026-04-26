# OBS-1: cedar-go silently drops unrecognized fields in policy JSON

**Severity:** Informational; not a crash, but may hide malformed inputs
**Class:** Silent diff; extra fields in input disappear from output

## Summary

cedar-go's `Policy.UnmarshalJSON` silently drops unknown fields at the policy level,
scope level, and condition level. The round-trip "succeeds" but the unknown fields are
not preserved. For the condition body, the behavior depends on the specific field.

## Examples

### D-001: Extra top-level policy field

Input: `{"effect": "permit", ..., "UNKNOWN_FIELD": "should be ignored or fail gracefully"}`

Output: `{"effect": "permit", ...}`; `UNKNOWN_FIELD` dropped silently.

cedar-go uses `encoding/json` with standard unmarshaling for the top-level `policyJSON`
struct. Unknown fields are silently ignored (no `DisallowUnknownFields` at the top level).

### D-002: Extra scope field

Input: `{"principal": {"op": "All", "extra": "ignored?"}, ...}`

Output: `{"principal": {"op": "All"}}`; `extra` dropped.

Same mechanism: `scopeJSON` struct does not use `DisallowUnknownFields`.

### D-003: Extra condition field

Input: `{"conditions": [{"kind": "when", "body": {...}, "extra": "ignored?"}]}`

Output: `{"conditions": [{"kind": "when", "body": {...}}]}`; `extra` dropped.

### D-005: Two ops in one body node (ambiguous)

Input body: `{"==": {"left": ..., "right": ...}, "!=": {"left": ..., "right": ...}}`

Outcome: cedar-go picks `==` (whichever Go JSON parser encounters first when
`DisallowUnknownFields` causes the fallback to `extensionJSON`). The `!=` op is
silently discarded.

Cedar text: `1 == 1` (only the `==` branch survives).

This is the more concerning case: an ambiguous node with two valid ops results in one
being silently dropped rather than an error.

## Honest assessment

Silent field dropping at the policy/scope/condition level is consistent with lenient JSON
parsing conventions. The condition-body ambiguity (two ops in one node) is more
surprising; cedar-go picks one winner silently.

The `nodeJSON.UnmarshalJSON` implementation uses `DisallowUnknownFields` for the first
decode attempt, then falls back to `extensionJSON` on failure. When a node has both a
known op (`==`) and an unknown field, the `DisallowUnknownFields` decode fails, and
the fallback to `extensionJSON` parses the whole object as an extension map. Then
`ToNode()` picks the first key via map iteration (non-deterministic in Go for small maps,
though effectively deterministic in practice for the known-op keys since they fall into
the struct path first).

Actually re-reading the code: the struct has explicit fields for `==`, `!=`, etc.
The first pass uses `DisallowUnknownFields` which would fail if there are two conflicting
ops. The behavior may depend on Go's JSON decode ordering.

## Affected probes

- `D-001-extra-policy-field` (silent drop; conformant behavior)
- `D-002-extra-scope-field` (silent drop; conformant behavior)
- `D-003-extra-condition-field` (silent drop; conformant behavior)
- `D-005-two-ops-in-node` (ambiguous; one op wins, non-deterministically)
- `E-002-action-in-both` (both `entity` and `entities` in action scope; `entity` wins)
