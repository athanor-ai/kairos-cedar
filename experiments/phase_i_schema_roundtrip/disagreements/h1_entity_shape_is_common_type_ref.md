# Phase I disagreement; h1_entity_shape_is_common_type_ref

**Schema-roundtrip widening of NEW-1 (cedar #1702 / cedar-go silent-diff
class).** Verified 2026-04-25.

## Versions
- cedar-policy-cli **4.10.0** (container `ghcr.io/athanor-ai/kairos-cedar:latest`)
- cedar-go **v1.6.0** (HEAD `a9a4b1b1450917d5df2a3c7c17d6567035fd8fcb`,
  `x/exp/schema`)
- Container hash: `d9c9ceb6be83`

## Hypothesis class
H1; entity-shape is a TypeRef naming a common type (NEW-1 #1702 territory).

## Input schema (JSON)

```json
{
  "": {
    "commonTypes": {
      "Foo": {
        "type": "Record",
        "attributes": {
          "bar": {
            "type": "Long"
          }
        }
      }
    },
    "entityTypes": {
      "Baz": {
        "shape": {
          "type": "Foo"
        }
      }
    },
    "actions": {}
  }
}
```

## cedar-policy 4.10.0; round-trip

- `cedar translate-schema --direction json-to-cedar` then
  `--direction cedar-to-json`.
- Classification: **parse_fail**
- × The following entities have shapes that cannot be converted to Cedar   │ schema syntax: [Baz]   help: Entity shapes may only be record types. In the Cedar schema syntax,         they additionally may not reference common type definitions.

## cedar-go v1.6.0 (`x/exp/schema`); round-trip

- `UnmarshalJSON` -> `MarshalCedar` -> `UnmarshalCedar` -> `MarshalJSON`.
- Classification: **silent_diff**
- $..entityTypes.Baz.shape.name: dropped; $..entityTypes.Baz.shape.type: 'EntityOrCommon' -> 'Record'

### cedar-go intermediate Cedar text

```cedar
type Foo = {
	bar: Long
};

entity Baz {};
```

### cedar-go final JSON (round-tripped)

```json
{"":{"entityTypes":{"Baz":{"shape":{"type":"Record"}}},"actions":{},"commonTypes":{"Foo":{"type":"Record","attributes":{"bar":{"type":"EntityOrCommon","name":"Long"}}}}}}
```

### cedar-go diff summary (input -> roundtripped)

`$..entityTypes.Baz.shape.name: dropped; $..entityTypes.Baz.shape.type: 'EntityOrCommon' -> 'Record'`

## Source-line attribution (cedar-go)

The fall-through is in
`cedar-go/x/exp/schema/internal/json/json.go::unmarshalNamespace`
(line 336) which calls `unmarshalRecordType` on `jet.Shape`
**unconditionally**, irrespective of `jet.Shape.Type`. When
`jet.Shape.Type` is anything other than `Record` (e.g. a TypeRef
naming a common-type, or a non-record primitive), the call produces
an empty `ast.RecordType`. The same root cause manifests in
`marshal.go::marshalDecls` (line 91) which always emits
`marshalRecordType(entity.Shape)`.

Equivalent root cause: `ast.Entity.Shape` is hard-typed as
`RecordType` (line 55 of `cedar-go/x/exp/schema/ast/ast.go`); the AST
cannot represent any non-record shape. Every JSON shape that is not a
Record-literal collapses on entry.

## Classification

**cross-format-asymmetric silent-diff**; cedar-policy errors honestly
on the JSON-only fragment, cedar-go silently transforms it.
