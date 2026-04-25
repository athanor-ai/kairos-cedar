# NEW-3: cedar-go MarshalCedar panics on ALL method-style extension calls with zero-arg array

**Severity:** Critical — attacker-controlled JSON crashes cedar-go process
**Class:** Extension of NEW-2 (offset) to all 18 method-style extension operators

## Summary

`Policy.UnmarshalJSON` succeeds when an extension method call is provided with an empty
argument array `[]`. The resulting AST node has `Args` of length 0. When
`Policy.MarshalCedar()` is subsequently called, `cedar_marshal.go:199` unconditionally
accesses `n.Args[0]`, triggering `runtime error: index out of range [0] with length 0`.

This affects all 18 method-style extension operators defined in `extensions.go`.

## Affected operators

| Operator | Expected arity | IsMethod |
|---|---|---|
| `lessThan` | 2 | true |
| `lessThanOrEqual` | 2 | true |
| `greaterThan` | 2 | true |
| `greaterThanOrEqual` | 2 | true |
| `isIpv4` | 1 | true |
| `isIpv6` | 1 | true |
| `isLoopback` | 1 | true |
| `isMulticast` | 1 | true |
| `isInRange` | 2 | true |
| `toDate` | 1 | true |
| `toTime` | 1 | true |
| `offset` | 2 | true |
| `durationSince` | 2 | true |
| `toDays` | 1 | true |
| `toHours` | 1 | true |
| `toMinutes` | 1 | true |
| `toSeconds` | 1 | true |
| `toMilliseconds` | 1 | true |

## Trigger

Any JSON policy condition body of the form `{"<method_name>": []}` where `<method_name>`
is any of the 18 method-style extensions:

```json
{
  "effect": "permit",
  "principal": {"op": "All"},
  "action": {"op": "All"},
  "resource": {"op": "All"},
  "conditions": [{"kind": "when", "body": {"isIpv4": []}}]
}
```

## Root cause

`cedar_marshal.go:195-214`, function `NodeTypeExtensionCall.marshalCedar`:

```go
func (n NodeTypeExtensionCall) marshalCedar(buf *bytes.Buffer) {
    var args []ast.IsNode
    info := extensions.ExtMap[n.Name]
    if info.IsMethod {
        marshalChildNode(n.precedenceLevel(), n.Args[0], buf)  // line 199 — PANICS if len(Args)==0
        buf.WriteRune('.')
        args = n.Args[1:]
    } else {
        args = n.Args
    }
    ...
}
```

The `UnmarshalJSON` path (via `extensionJSON.ToNode`) does not validate arity before
building the AST node. The marshal path assumes `len(n.Args) >= 1` for method calls.

## cedar-policy (Rust) behavior

The Rust cedar-policy CLI *accepts* the same malformed input and emits valid Cedar text:

```
permit(principal, action, resource) when { isIpv4() };
```

Rust does not validate arity at parse time — it emits `ext_name()` with zero args.
The AST would fail at type-checking / evaluation, but the marshaller does not crash.

**Cross-impl verdict:** cedar-go panics; Rust produces `method_name()` text (malformed
Cedar semantics, but no crash). This is a behavioral divergence: Rust silently accepts
invalid arity, cedar-go crashes. Neither enforces arity at the JSON→AST boundary.

## Fix

In `extensionJSON.ToNode()` or `NodeTypeExtensionCall.marshalCedar()`: validate that
`len(args) >= 1` for method-style calls before accessing `n.Args[0]`. Return an error
at unmarshal time, or guard the marshal path with a bounds check.

Proposed fix location: `cedar-go/internal/json/json.go`, `extensionJSON.ToNode()`:

```go
func (e extensionJSON) ToNode() (ast.Node, error) {
    ...
    info, ok := extensions.ExtMap[types.Path(k)]
    if ok && info.IsMethod && len(v) == 0 {
        return ast.Node{}, fmt.Errorf("method %q requires at least 1 argument (receiver), got 0", k)
    }
    ...
}
```

## Probe inputs (all panics confirmed)

```
B-zero-lessThan, B-zero-lessThanOrEqual, B-zero-greaterThan, B-zero-greaterThanOrEqual,
B-zero-isIpv4, B-zero-isIpv6, B-zero-isLoopback, B-zero-isMulticast, B-zero-isInRange,
B-zero-toDate, B-zero-toTime, B-zero-offset, B-zero-durationSince,
B-zero-toDays, B-zero-toHours, B-zero-toMinutes, B-zero-toSeconds, B-zero-toMilliseconds
```

All 18 confirmed panics from `/tmp/go_results.ndjson` outcome=panic.
