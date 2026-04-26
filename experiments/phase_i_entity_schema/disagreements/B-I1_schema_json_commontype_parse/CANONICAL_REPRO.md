# Disagreement B-I1: cedar-go's schema JSON unmarshaller rejects Rust's CommonTypeRef wire form

**Date:** 2026-04-26
**Filed by:** platform agent (`phase_i_entity_schema`)
**Severity:** parse error (cedar-go returns error on valid Rust-emitted schema JSON)

***

## Versions under test

| Impl | Version | Source |
| :- | :- | :- |
| cedar-policy (Rust) | 4.10.0 | `/work/cedar-spec/cedar` workspace pin, commit `6e0f25b` (2026-04-21) |
| cedar-go (Go) | HEAD on `main` | `/work/cedar-go`, commit `a9a4b1b` (2026-03-20) |
| Lean evaluator | n/a | spec-source-read attribution only |

## Input: schema JSON using Rust's CommonTypeRef form

Rust cedar-policy serialises a reference to a common type `Address` as:

```json
{"type": "Address"}
```

(the common type name is the value of the `"type"` field, with no `"name"` sibling key).

Complete input schema:

```json
{
  "": {
    "commonTypes": {
      "Address": {
        "type": "Record",
        "attributes": {
          "street": {"type": "String"},
          "zip": {"type": "String"}
        }
      }
    },
    "entityTypes": {
      "User": {
        "shape": {
          "type": "Record",
          "attributes": {
            "addr": {"type": "Address"}
          }
        }
      }
    },
    "actions": {}
  }
}
```

## Rust output (cedar-policy 4.10.0)

```
--- Schema Test 1: CommonTypeRef bare form (Rust native parse+emit) ---
  OK: Parsed CommonTypeRef bare form
  Re-emits bare 'Address' (CommonTypeRef form): true
  Re-emits 'EntityOrCommon': false
  === FULL OUTPUT ===
{
  "": {
    "commonTypes": { "Address": { "type": "Record", ... } },
    "entityTypes": {
      "User": {
        "shape": {
          "type": "Record",
          "attributes": {
            "addr": { "type": "Address" }
          }
        }
      }
    },
    "actions": {}
  }
}
```

Rust 4.10.0:
- **Parses** `{"type": "Address"}` successfully (falls through to `Type::CommonTypeRef` in its custom deserializer when the `type` value is not a known keyword)
- **Re-emits** the same `{"type": "Address"}` form on serialization

## cedar-go output

```
--- PROBE 1: Parse Rust CommonTypeRef bare form ---
  Input has {"type": "Address"} (the Rust native CommonTypeRef wire form)
  RESULT: PARSE ERROR — namespace "": entity "User" shape: attribute "addr": unknown type "Address"
  VERDICT: cedar-go cannot parse Rust-emitted schema JSON for CommonTypeRef
```

cedar-go 1.6.0:
- **Fails** with `unknown type "Address"` — the `unmarshalType` switch in
  `x/exp/schema/internal/json/json.go:395-423` only handles:
  `"String"`, `"Long"`, `"Boolean"`, `"Extension"`, `"Set"`, `"Record"`,
  `"Entity"`, `"EntityOrCommon"`. Any other string → `fmt.Errorf("unknown type %q", jt.Type)`.

## cedar-go's own form (accepted by both)

cedar-go serialises the same reference as `{"type": "EntityOrCommon", "name": "Address"}`.
Rust also accepts this form — both impls parse `EntityOrCommon`. The difference is
in the **serialization direction**: Rust emits bare `"type":"Address"`, cedar-go emits
`"type":"EntityOrCommon","name":"Address"`. These are non-interoperable on the parse path.

```
--- PROBE 2: cedar-go EntityOrCommon round-trip ---
  Parsed OK; round-trip identity: true

--- Schema Test 2: EntityOrCommon explicit tag (cedar-go format) ---
  OK: Parsed EntityOrCommon form
  Re-emits bare 'Address': false
  Re-emits 'EntityOrCommon': true
```

## Source attribution

* **Rust** `cedar-policy-core/src/validator/json_schema.rs:2046-2052`: the custom
  `TypeVisitor` deserialiser falls through to `Type::CommonTypeRef` for any `type`
  field value not matching `"String"`, `"Long"`, `"Boolean"`, `"Set"`, `"Record"`,
  `"Entity"`, `"EntityOrCommon"`, `"Extension"`.
* **Rust** `cedar-policy-core/src/validator/json_schema.rs:1341-1395`:
  `Type::CommonTypeRef` is `#[serde(untagged)]` with a `#[serde(rename = "type")]`
  field on `type_name`, so it serialises directly as `{"type": "<name>"}`.
* **cedar-go** `x/exp/schema/internal/json/json.go:395-423`: `unmarshalType` switch
  on `jt.Type` has no `default:` catch-all for bare common-type names.
* **cedar-go** `x/exp/schema/internal/json/json.go:253-256`: `marshalIsType` for
  `ast.TypeRef` emits `{"type":"EntityOrCommon","name":"<name>"}`.
* **Lean spec** `Cedar/Validation/Types.lean` does not specify the JSON schema wire
  format; the divergence is at the JSON-schema-format layer only. The Lean spec
  resolves all type references before validation (no `CommonTypeRef` concept in the
  formal model — only resolved `CedarType`).

## Does this affect policy decisions?

**Not directly at evaluation time** — the parse error occurs *before* evaluation.
A Rust-emitting pipeline that writes a schema JSON then passes it to cedar-go for
validation will receive a hard parse error and fail to validate any policies.

## Classification

**New B-class**: `B-I1` — schema JSON **parse incompatibility**.

Unlike B0/B1.x/B2.x which are wire-format divergences that still let the receiver
interpret a value, this is a **hard parse failure**: cedar-go completely rejects
valid Rust-emitted schema JSON. Any pipeline using Rust to write schemas and
cedar-go to read them breaks unless the schemas use only built-in types (no `commonTypes`).

## Reproducer paths

* `experiments/phase_i_entity_schema/repros/schema_json_roundtrip/{go.mod,go.sum,main.go}` — Go probe
* `experiments/phase_i_entity_schema/repros/rust_entity_schema/{Cargo.toml,main.rs}` — Rust probe
