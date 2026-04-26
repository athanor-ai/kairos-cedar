# Canonical Reproducer - cedar #1702 (entity shape uses common type)

**Issue:** https://github.com/cedar-policy/cedar/issues/1702
**Title:** "JSON schema defining entity attributes entirely with a common type cannot be represented as Cedar schema"
**State at probe time:** open (verified 2026-04-25)

## Summary

The cedar #1702 reporter notes that a JSON schema where an entity's shape
*is* a common type (rather than an inline record) cannot be expressed in
Cedar-text schema syntax. We reproduced the Rust-side limitation on the
pinned 4.10.0 reference. While verifying the bug in cedar-go, we found
**a separate, more serious cedar-go bug**: cedar-go's experimental schema
package silently round-trips the same JSON schema to a Cedar-text schema
that is semantically different from the original (the common-type
reference is dropped, leaving an empty entity shape).

## Versions

- `cedar-policy-cli` **4.10.0** (Rust reference, container
  `ghcr.io/athanor-ai/kairos-cedar:latest`, image hash `d9c9ceb6be83`)
- `cedar-go` **v1.6.0** (HEAD `a9a4b1b1450917d5df2a3c7c17d6567035fd8fcb`,
  experimental package `github.com/cedar-policy/cedar-go/x/exp/schema`)
- Lean evaluator: **N/A** - `cedar-spec/cedar-lean` formalizes the
  authorizer / evaluator over a parsed schema; it does not implement the
  Cedar-text-schema parser, so it does not contribute a verdict on
  schema-format round-trip questions.

## Inputs

### JSON schema (input)

```json
{
  "": {
    "commonTypes": {
      "Foo": {
        "type": "Record",
        "attributes": { "bar": { "type": "Long" } }
      }
    },
    "entityTypes": {
      "Baz": { "shape": { "type": "Foo" } }
    },
    "actions": {}
  }
}
```

### Cedar-text schema (the form #1702 wishes were valid)

```cedar
type Foo = { bar: Long };
entity Baz = Foo;
```

## Verdicts

### Rust `cedar` 4.10.0

- `cedar check-parse --schema schema.json --schema-format json` → **rc=0** (JSON parses).
- `cedar check-parse --schema schema.cedarschema` → **rc=1**:

  ```
  error parsing schema: unexpected token `Foo`
   ╭─[2:14]
   1 │ type Foo = { bar: Long };
   2 │ entity Baz = Foo;
     ·              ─┬─
     ·               ╰── expected `{`
  ```
- `cedar translate-schema --direction json-to-cedar -s schema.json` → **rc=1**:

  ```
  × The following entities have shapes that cannot be converted to Cedar
  │ schema syntax: [Baz]
  help: Entity shapes may only be record types. In the Cedar schema syntax,
        they additionally may not reference common type definitions.
  ```

  Rust correctly recognizes the schema is in the JSON-only fragment of
  the schema language and refuses to translate.

### cedar-go v1.6.0 (`x/exp/schema`)

`UnmarshalJSON` succeeds, then `MarshalCedar` succeeds and emits:

```cedar
type Foo = {
	bar: Long
};

entity Baz {};
```

The marshalled Cedar text is **not** semantically equivalent to the input
JSON. The original `Baz` entity has shape `Foo` (so `Baz::"x".bar` is a
`Long`), but the marshalled text gives `Baz` an empty record shape (so
`Baz::"x".bar` is an undeclared attribute access). The marshaller
silently dropped the common-type reference.

Re-parsing the marshalled Cedar with `UnmarshalCedar` succeeds (it parses
as the empty-shape entity), so cedar-go's pipeline produces a
schema-equivalence violation on round-trip.

Reproducer command (from worktree root):

```bash
./scripts/dc bash -c '
  cd /work/experiments/phase_c_diff/open-issues-2026-04-25/disagreements/issue_1_common_type_entity_shape/go_roundtrip
  GOFLAGS="-mod=mod -buildvcs=false" go build -o probe . && \
    ./probe /work/experiments/phase_c_diff/open-issues-2026-04-25/disagreements/issue_1_common_type_entity_shape/schema.json
'
```

Output:

```
UNMARSHAL_JSON_OK
MARSHAL_CEDAR_OK
---- BEGIN MARSHALLED CEDAR ----
type Foo = {
	bar: Long
};

entity Baz {};
---- END MARSHALLED CEDAR ----
ROUNDTRIP_REPARSE_OK
```

## Classification

**reproduced + adjacent-bug-surfaced.**

- `cedar` #1702 is **reproduced** on Rust 4.10.0 (Cedar-text schema parser
  rejects what the JSON-schema parser accepts; the docs reporter's
  example is faithful).
- An **adjacent cedar-go bug** is surfaced by attempting the same
  round-trip in cedar-go's `x/exp/schema`: cedar-go silently emits
  semantically-different Cedar text. Where Rust treats the JSON-only
  fragment as an honest error, cedar-go treats it as a successful
  marshal that drops information. This is the same architectural
  pattern as the bug-hunt-2026-04-25 findings (cedar-go ext-type parsers
  delegate to stdlib that accepts Cedar-grammar-supersets): cedar-go's
  schema marshaller's traversal of the entity-shape AST does not handle
  the `commonType-reference` shape and falls through to the
  inline-record case, producing an empty record.

Per the bug-hunt convention this would be classified
**cross-format-asymmetric** with a decision-flip side effect (any
policy referencing `principal.bar` would type-check against the
original JSON schema but fail against the round-tripped Cedar-text
schema).

## Source-line citation (cedar-go marshaller)

The marshalled empty `entity Baz {}` is emitted by the Cedar-text
schema marshaller in `cedar-go/x/exp/schema/internal/parser` (the
package imported as `parser` in
`cedar-go/x/exp/schema/schema.go::MarshalCedar`). The traversal of the
entity-shape AST does not encode the case where `shape` is a
`commonType` reference rather than an inline record; the silent
fallthrough to the empty-record case is the bug.

(Citation requested by the task spec: line 45 of
`/work/cedar-go/x/exp/schema/schema.go` calls
`parser.MarshalSchema(s.astOrEmpty())`; the buggy branch is inside
that `MarshalSchema` walker.)

## Honest reporting

- The behavior #1702 reports **does** still reproduce on cedar 4.10.0
  Rust: the Cedar-text-schema parser cannot express the JSON-only
  fragment.
- The cedar-go round-trip behavior reported here was **not** the focus
  of #1702 but is an adjacent finding worth filing upstream.
