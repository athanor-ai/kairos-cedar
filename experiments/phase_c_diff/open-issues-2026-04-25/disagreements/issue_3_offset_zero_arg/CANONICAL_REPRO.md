# Canonical Reproducer - cedar #2116 (zero-arg method-style call)

**Issue:** https://github.com/cedar-policy/cedar/issues/2116
**Title:** "JSON policy with zero-argument method style call doesn't parse when converted to Cedar syntax"
**State at probe time:** open (verified 2026-04-25)

## Summary

The reporter notes that a JSON policy can encode `{"offset": []}` -
the extension function `offset` called with zero arguments - and the
JSON parser accepts it. When this is converted to Cedar text via
`cedar translate-policy`, the emitted text is `offset()`, which fails
to re-parse because `offset` is a method-style extension call (must be
written `e.offset(...)` with at least one self argument).

The probe **reproduces** this on cedar 4.10.0 Rust. Probing the same
JSON policy through cedar-go v1.6.0 surfaces an **adjacent, more
severe cedar-go bug**: cedar-go's `Policy.MarshalCedar` **panics**
(`index out of range [0] with length 0`) on the same input rather
than emitting an invalid-but-honest `offset()`.

## Versions

- `cedar-policy-cli` **4.10.0** (Rust reference)
- `cedar-go` **v1.6.0** (HEAD `a9a4b1b`)
- Lean evaluator: parses the JSON form, sees an `ExtensionCall offset
  []`, and rejects at type-check / arity-check time. Lean **agrees with
  the JSON-parse-then-evaluate semantics** (the Rust runtime, given the
  parsed JSON, would also error at evaluate time on arity mismatch).
  See `cedar-spec/cedar-lean/Cedar/Spec/Ext/Datetime.lean` for the
  signature `offset : Datetime → Duration → Datetime`.

## Inputs

### JSON policy (single-policy form for cedar-go)

```json
{
  "effect": "permit",
  "principal": { "op": "==", "entity": { "type": "User", "id": "bob" } },
  "resource":  { "op": "==", "entity": { "type": "User", "id": "bob" } },
  "action": { "op": "All" },
  "conditions": [
    { "kind": "when", "body": { "offset": [] } }
  ]
}
```

(For Rust the same body is wrapped in `{"templates":{},"staticPolicies":{"policy0":{...}},"templateLinks":[]}`.)

### Synthesized Cedar text (the round-trip target)

```cedar
permit(
  principal == User::"bob",
  action,
  resource == User::"bob"
) when {
  offset()
};
```

## Verdicts

| Implementation | Pipeline step | Result |
|----|----|----|
| `cedar-policy` 4.10.0 (Rust) | `check-parse --policy-format json` | rc=0 (JSON parse OK) |
| `cedar-policy` 4.10.0 (Rust) | `translate-policy --direction json-to-cedar` | rc=0, emits `offset()` |
| `cedar-policy` 4.10.0 (Rust) | re-parse the emitted Cedar text | rc=1, `offset is a method, not a function` |
| `cedar-go` v1.6.0 | `Policy.UnmarshalJSON` | OK |
| `cedar-go` v1.6.0 | authorize on the parsed policy | **Deny** with diagnostic `wrong number of arguments provided to extension function: offset takes 2 parameter(s), but 0 provided` |
| `cedar-go` v1.6.0 | `Policy.MarshalCedar` | **runtime panic**: `index out of range [0] with length 0` at `internal/parser/cedar_marshal.go:199` |

The cedar-go panic is on the same logical pipeline step as the Rust
failure (round-tripping JSON-parse → Cedar-text-emit), but cedar-go
fails *harder*: an unrecovered panic instead of a translation that
produces invalid Cedar text.

## Reproducer commands

### Rust round-trip (issue #2116 itself)

```bash
DIR=/work/experiments/phase_c_diff/open-issues-2026-04-25/disagreements/issue_3_offset_zero_arg
./scripts/dc bash -c "
cedar translate-policy --direction json-to-cedar --policies $DIR/policy_set.json > /tmp/out.cedar
cedar check-parse --policies /tmp/out.cedar
# → rc=1, 'offset is a method, not a function'
"
```

### cedar-go panic on MarshalCedar

```bash
./scripts/dc bash -c "
cd /work/experiments/phase_c_diff/open-issues-2026-04-25/disagreements/issue_3_offset_zero_arg/go_marshalcedar
GOFLAGS='-mod=mod -buildvcs=false' go build -o probe .
./probe /work/experiments/phase_c_diff/open-issues-2026-04-25/disagreements/issue_3_offset_zero_arg/policy_single.json
# → UNMARSHAL_JSON_OK
# → panic: runtime error: index out of range [0] with length 0
#   at internal/parser/cedar_marshal.go:199
"
```

### cedar-go authorize (no panic - diagnostic path)

```bash
./scripts/dc bash -c "
cd /work/experiments/phase_c_diff/open-issues-2026-04-25
ENT=fixtures/entities.json
echo '{\"idx\":\"j\",\"principal\":\"User::bob\",\"action\":\"Action::view\",\"resource\":\"User::bob\",\"policy_path\":\"/work/experiments/phase_c_diff/open-issues-2026-04-25/disagreements/issue_3_offset_zero_arg/policy_single.json\",\"policy_format\":\"json\"}' \
  | ./go_harness_json/probe \$ENT
# → {\"idx\":\"j\",\"decision\":\"Deny\",\"diagnostic\":\"wrong number of arguments provided to extension function: offset takes 2 parameter(s), but 0 provided; \"}
"
```

## Classification

**reproduced + adjacent-severity-bug-surfaced.**

- `cedar` #2116 reproduces on Rust 4.10.0 exactly as filed.
- cedar-go inherits the same JSON-vs-Cedar-text grammar gap. On the
  authorize path it converts to a graceful diagnostic (Deny), but on
  the MarshalCedar path it **panics** rather than returning an error.

Per the bug-hunt convention this is **cross-format-asymmetric** with a
**panic-on-unfixable-input side effect** in cedar-go. The panic
specifically is paper-grade: an attacker-controlled JSON policy
crashes the cedar-go marshaller via an unchecked
`Args[0]` access in the method-style branch.

## Source-line citation (cedar-go)

`/work/cedar-go/internal/parser/cedar_marshal.go:199`:

```go
func (n NodeTypeExtensionCall) marshalCedar(buf *bytes.Buffer) {
	var args []ast.IsNode
	info := extensions.ExtMap[n.Name]
	if info.IsMethod {
		marshalChildNode(n.precedenceLevel(), n.Args[0], buf)  // ← line 199, panics on len==0
		buf.WriteRune('.')
		args = n.Args[1:]
	} else {
		args = n.Args
	}
	...
}
```

Fix would be to guard with `if len(n.Args) == 0 { return error }` or
to detect this case at JSON-unmarshal time (matching cedar #2116's
preferred fix in Rust).

This matches the bug-hunt-2026-04-25 architectural pattern: cedar-go's
JSON-paths are wider than the Cedar-text grammar, and the gap shows
up wherever Cedar-text-grammar invariants are assumed downstream of a
JSON-parsed AST.

## Honest reporting

- `cedar` #2116 reproduces on the pinned Rust reference.
- cedar-go **does not** reproduce the exact Rust failure (it does not
  emit `offset()`); the cedar-go failure mode is more severe (panic).
- The cedar-go panic is a **new bug** observed while testing #2116.
  Recommend filing as a separate cedar-go issue.
