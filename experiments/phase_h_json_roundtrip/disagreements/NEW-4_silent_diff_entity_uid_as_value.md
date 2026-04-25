# NEW-4: cedar-go silently changes entity-UID-as-Value to Record on JSON round-trip

**Severity:** Medium — JSON round-trip not identity; information representation changes
**Class:** Silent diff on conformant input

## Summary

When a Cedar JSON policy uses `{"Value": {"type": "User", "id": "alice"}}` to represent
an entity UID literal, cedar-go's round-trip changes the representation to
`{"Record": {"id": {"Value": "alice"}, "type": {"Value": "User"}}}`.

The Cedar JSON format distinguishes entity UIDs from records: entity UIDs should be
represented as `{"Value": {"__entity": {"type": "...", "id": "..."}}}`. However,
cedar-go's JSON→AST→JSON path converts input entity-UID-as-raw-dict into a Record AST
node during MarshalJSON.

## Example probe (A-032-in-expr, F-009-entity-uid-value)

Input:
```json
{
  "effect": "permit",
  "principal": {"op": "All"},
  "action": {"op": "All"},
  "resource": {"op": "All"},
  "conditions": [{"kind": "when", "body": {
    "in": {
      "left": {"Var": "principal"},
      "right": {"Set": [{"Value": {"type": "Group", "id": "admins"}}]}
    }
  }}]
}
```

Cedar text produced (correct): `permit(...) when { principal in [{"id": "admins", "type": "Group"}] };`

Output JSON (differs from input):
```json
{
  "conditions": [{"kind": "when", "body": {
    "in": {
      "left": {"Var": "principal"},
      "right": {"Set": [{"Record": {"id": {"Value": "admins"}, "type": {"Value": "Group"}}}]}
    }
  }}]
}
```

The Cedar text is semantically ambiguous — `{"id": "admins", "type": "Group"}` is a
record literal in Cedar text, not an entity UID. Cedar-go reads it back as a Record.

## Root cause

The JSON `Value` field unmarshaling (via `types.UnmarshalJSON`) interprets
`{"type": "...", "id": "..."}` as an entity UID at JSON→AST time. When cedar-go
marshals the Cedar text, a record literal `{"id": "...", "type": "..."}` appears.
When that Cedar text is then parsed back, cedar-go has no way to distinguish a
record literal from an entity UID — it parses as `Record`.

The standard entity UID JSON representation is `{"__entity": {"type": "...", "id": "..."}}`.
The probe input used the non-standard short form `{"type": "...", "id": "..."}` which
cedar-go accepts as entity UID but cannot faithfully round-trip.

## Honest assessment

This is a **semi-conformant** input: the short form `{"type":"...","id":"..."}` is an
entity UID encoding documented in the Cedar types JSON format, but the Cedar text
representation of entity UIDs (`EntityType::"id"`) is what MarshalCedar emits.
When reading back from Cedar text, the entity UID becomes an entity-UID AST node,
which marshals back to `{"Value": {"__entity": ...}}` — but *only* if the Cedar text
parser can resolve it. In this specific case (entity UID in a `Set` literal), the
Cedar text parser reads it as a Record, causing the representation change.

The round-trip **does change the AST type** (entity UID → record), which is a genuine
behavioral difference even if the Cedar evaluation semantics differ.

## cedar-policy (Rust) behavior

The Rust cedar translate-policy rejects the input `{"Value": {"type":"Group","id":"admins"}}`
with an error:
```
missing field `__entity`
```
Rust requires the `__entity` envelope for entity UIDs in the JSON policy format.

**Cross-impl verdict:** cedar-go accepts the short-form entity UID and silently changes
its type on round-trip. Rust rejects the input. This is a cross-impl acceptance divergence.

## Affected probes

- `A-032-in-expr` — entity UID in Set literal
- `F-009-entity-uid-value` — entity UID as direct value
- `A-025b-is-in-expr` — entity UID in is-in expression
