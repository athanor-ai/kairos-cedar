# NEW-6: cedar-go changes extension value form `{__extn: {fn, arg}}` to call form `{fn: [arg]}` on round-trip

**Severity:** Medium — JSON representation changes on round-trip; consumers of the JSON format may not handle both forms
**Class:** Silent diff on conformant input

## Summary

The Cedar JSON format supports two ways to embed extension type values (e.g., IP addresses):
1. **Value form**: `{"Value": {"__extn": {"fn": "ip", "arg": "192.168.1.1"}}}` — extension value embedded inside a `Value` node
2. **Call form**: `{"ip": [{"Value": "192.168.1.1"}]}` — extension call expression

Both forms are valid Cedar JSON. When cedar-go receives the value form and round-trips
it through Cedar text, the output uses the call form. They are semantically equivalent
(both evaluate to `ip("192.168.1.1")`), but JSON round-trip is not identity.

## Example probe (F-010-ip-value)

Input:
```json
{"Value": {"__extn": {"fn": "ip", "arg": "192.168.1.1"}}}
```

Cedar text produced: `ip("192.168.1.1")` (extension call form in Cedar text)

Output JSON:
```json
{"ip": [{"Value": "192.168.1.1"}]}
```

The Cedar text `ip("192.168.1.1")` parses as a function call, not as a value literal.
When marshalled to JSON, it becomes the call form `{"ip": [...]}`.

## Root cause

Cedar text has only one representation for extension type values: the function call form.
When `{"Value": {"__extn": ...}}` is parsed from JSON, it creates a `Value` AST node.
When marshalled to Cedar text, it becomes an extension call expression (e.g., `ip("192.168.1.1")`).
When that Cedar text is re-parsed, it creates an `ExtensionCall` AST node, not a `Value` node.
The final JSON form differs from the input.

This is an inherent limitation of the Cedar text format: extension type values cannot
be distinguished from extension function calls in Cedar text.

## Honest assessment

Both representations are semantically equivalent at evaluation time. The JSON→Cedar→JSON
round-trip necessarily changes the form because Cedar text conflates function-call syntax
with value construction for extension types.

This is a **known limitation** of the JSON↔text round-trip for extension types, not a
bug in cedar-go specifically. However, consumers should be aware that the value form
`{"Value": {"__extn": ...}}` does not survive round-trip as identity.

## cedar-policy (Rust) behavior

The Rust cedar translate-policy appears to reject `{"Value": {"__extn": ...}}` in the
policy expression position (it expects extension type values to be expressed differently
in that context). The exact behavior differs from cedar-go.

## Affected probes

- `F-010-ip-value`
