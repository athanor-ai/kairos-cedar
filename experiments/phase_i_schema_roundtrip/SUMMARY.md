# Phase I; schema-roundtrip widening: SUMMARY

Date: 2026-04-25

Versions:
- cedar-policy-cli **4.10.0** (container `ghcr.io/athanor-ai/kairos-cedar:latest`, image hash `d9c9ceb6be83`)
- cedar-go **v1.6.0** (HEAD `a9a4b1b1450917d5df2a3c7c17d6567035fd8fcb`, `x/exp/schema`)
- Lean evaluator: N/A; `cedar-spec/cedar-lean` does not implement the Cedar-text-schema parser, so it does not contribute a verdict on schema-format round-trip.

## Aggregate

- N_schemas tested: **21**
- N_well-formed (cedar 4.10.0 `check-parse` rc=0): **21**

Counts on the well-formed subset only (per the task's honesty rule; ill-formed inputs are generator bugs, not marshaller findings):

- cedar-policy: clean=16, silent_diff=0, parse_fail=5
- cedar-go: clean=8, silent_diff=4, parse_fail=9, panic=0

## Per-shape table

| Schema id | Hypothesis | well-formed | cedar-policy | cedar-go | Filed under disagreements/? |
|-----------|------------|-------------|--------------|----------|-----------------------------|
| `h1_entity_shape_is_common_type_ref` | H1 | yes | `parse_fail` | `silent_diff` | yes |
| `h1b_entity_shape_is_common_type_ref_with_optional` | H1 | yes | `parse_fail` | `silent_diff` | yes |
| `h1c_entity_shape_is_namespaced_common_type_ref` | H1 | yes | `parse_fail` | `silent_diff` | yes |
| `h1d_entity_shape_is_entityorcommon_typeref` | H1 | yes | `parse_fail` | `silent_diff` | yes |
| `h1e_chained_common_types` | H1 | yes | `parse_fail` | `parse_fail` | no |
| `h3_record_attr_aliases_long` | H3 | yes | `clean` | `parse_fail` | no |
| `h3b_record_attr_aliases_set` | H3 | yes | `clean` | `parse_fail` | no |
| `h3c_record_attr_nested_common_type_ref` | H3 | yes | `clean` | `parse_fail` | no |
| `h4_three_namespaces_cross_ref` | H4 | yes | `clean` | `parse_fail` | no |
| `h5_three_level_entity_hierarchy` | H5 | yes | `clean` | `clean` | no |
| `h5b_diamond_entity_hierarchy` | H5 | yes | `clean` | `clean` | no |
| `h6_tagged_entity_primitive_tags` | H6 | yes | `clean` | `clean` | no |
| `h6b_tagged_entity_tags_is_common_type_ref` | H6 | yes | `clean` | `parse_fail` | no |
| `h6c_tagged_entity_tags_set` | H6 | yes | `clean` | `clean` | no |
| `h6d_tagged_entity_tags_is_record_common_type_ref` | H6 | yes | `clean` | `parse_fail` | no |
| `h7_action_context_common_type_ref` | H7 | yes | `clean` | `parse_fail` | no |
| `h7b_multi_action_multi_resource_appliesto` | H7 | yes | `clean` | `clean` | no |
| `h8_decimal_attr` | H8 | yes | `clean` | `clean` | no |
| `h8b_ipaddr_attr` | H8 | yes | `clean` | `clean` | no |
| `h8c_datetime_and_duration_attrs` | H8 | yes | `clean` | `clean` | no |
| `h8d_extension_in_common_type` | H8 | yes | `clean` | `parse_fail` | no |

## Per-shape detail

### `h1_entity_shape_is_common_type_ref`

_H1; entity-shape is a TypeRef naming a common type (NEW-1 #1702 territory)._

- **cedar-policy:** `parse_fail`; `× The following entities have shapes that cannot be converted to Cedar   │ schema syntax: [Baz]   help: Entity shapes may only be record types. In the Cedar schema syntax,         they additionally ma`
- **cedar-go:** `silent_diff`; diff `$..entityTypes.Baz.shape.name: dropped; $..entityTypes.Baz.shape.type: 'EntityOrCommon' -> 'Record'`

### `h1b_entity_shape_is_common_type_ref_with_optional`

_H1; entity-shape is a TypeRef naming a common type (NEW-1 #1702 territory)._

- **cedar-policy:** `parse_fail`; `× The following entities have shapes that cannot be converted to Cedar   │ schema syntax: [Baz]   help: Entity shapes may only be record types. In the Cedar schema syntax,         they additionally ma`
- **cedar-go:** `silent_diff`; diff `$..commonTypes.Foo.attributes.opt.required: dropped; $..entityTypes.Baz.shape.name: dropped; $..entityTypes.Baz.shape.type: 'EntityOrCommon' -> 'Record'`

### `h1c_entity_shape_is_namespaced_common_type_ref`

_H1; entity-shape is a TypeRef naming a common type (NEW-1 #1702 territory)._

- **cedar-policy:** `parse_fail`; `× The following entities have shapes that cannot be converted to Cedar   │ schema syntax: [NS::Baz]   help: Entity shapes may only be record types. In the Cedar schema syntax,         they additionall`
- **cedar-go:** `silent_diff`; diff `$.NS.entityTypes.Baz.shape.name: dropped; $.NS.entityTypes.Baz.shape.type: 'EntityOrCommon' -> 'Record'`

### `h1d_entity_shape_is_entityorcommon_typeref`

_H1; entity-shape is a TypeRef naming a common type (NEW-1 #1702 territory)._

- **cedar-policy:** `parse_fail`; `× The following entities have shapes that cannot be converted to Cedar   │ schema syntax: [Baz]   help: Entity shapes may only be record types. In the Cedar schema syntax,         they additionally ma`
- **cedar-go:** `silent_diff`; diff `$..entityTypes.Baz.shape.name: dropped; $..entityTypes.Baz.shape.type: 'EntityOrCommon' -> 'Record'`

### `h1e_chained_common_types`

_H1; entity-shape is a TypeRef naming a common type (NEW-1 #1702 territory)._

- **cedar-policy:** `parse_fail`; `× The following entities have shapes that cannot be converted to Cedar   │ schema syntax: [Baz]   help: Entity shapes may only be record types. In the Cedar schema syntax,         they additionally ma`
- **cedar-go:** `parse_fail`; `namespace "": common type "Outer": attribute "inner": unknown type "Inner"`

### `h3_record_attr_aliases_long`

_H3; record attr type is a TypeRef (common-type alias of primitive / set / record)._

- **cedar-policy:** `clean` (round-trips byte-equivalent)
- **cedar-go:** `parse_fail`; `namespace "": entity "Baz" shape: attribute "n": unknown type "MyLong"`

### `h3b_record_attr_aliases_set`

_H3; record attr type is a TypeRef (common-type alias of primitive / set / record)._

- **cedar-policy:** `clean` (round-trips byte-equivalent)
- **cedar-go:** `parse_fail`; `namespace "": entity "Baz" shape: attribute "tags": unknown type "MySet"`

### `h3c_record_attr_nested_common_type_ref`

_H3; record attr type is a TypeRef (common-type alias of primitive / set / record)._

- **cedar-policy:** `clean` (round-trips byte-equivalent)
- **cedar-go:** `parse_fail`; `namespace "": entity "Baz" shape: attribute "inner": unknown type "Inner"`

### `h4_three_namespaces_cross_ref`

_H4; multi-namespace cross-references._

- **cedar-policy:** `clean` (round-trips byte-equivalent)
- **cedar-go:** `parse_fail`; `namespace "C": entity "CE" shape: attribute "a": unknown type "A::AT"`

### `h5_three_level_entity_hierarchy`

_H5; entity hierarchies with deep / wide `in` chains._

- **cedar-policy:** `clean` (round-trips byte-equivalent)
- **cedar-go:** `clean` (round-trips byte-equivalent)

### `h5b_diamond_entity_hierarchy`

_H5; entity hierarchies with deep / wide `in` chains._

- **cedar-policy:** `clean` (round-trips byte-equivalent)
- **cedar-go:** `clean` (round-trips byte-equivalent)

### `h6_tagged_entity_primitive_tags`

_H6; RFC-82 tagged entities (tags type variants)._

- **cedar-policy:** `clean` (round-trips byte-equivalent)
- **cedar-go:** `clean` (round-trips byte-equivalent)

### `h6b_tagged_entity_tags_is_common_type_ref`

_H6; RFC-82 tagged entities (tags type variants)._

- **cedar-policy:** `clean` (round-trips byte-equivalent)
- **cedar-go:** `parse_fail`; `namespace "": entity "Resource" tags: unknown type "TagT"`

### `h6c_tagged_entity_tags_set`

_H6; RFC-82 tagged entities (tags type variants)._

- **cedar-policy:** `clean` (round-trips byte-equivalent)
- **cedar-go:** `clean` (round-trips byte-equivalent)

### `h6d_tagged_entity_tags_is_record_common_type_ref`

_H6; RFC-82 tagged entities (tags type variants)._

- **cedar-policy:** `clean` (round-trips byte-equivalent)
- **cedar-go:** `parse_fail`; `namespace "": entity "Resource" tags: unknown type "TagRec"`

### `h7_action_context_common_type_ref`

_H7; action context as common-type ref + multi-action multi-resource appliesTo blocks._

- **cedar-policy:** `clean` (round-trips byte-equivalent)
- **cedar-go:** `parse_fail`; `namespace "": action "view" context: unknown type "Ctx"`

### `h7b_multi_action_multi_resource_appliesto`

_H7; action context as common-type ref + multi-action multi-resource appliesTo blocks._

- **cedar-policy:** `clean` (round-trips byte-equivalent)
- **cedar-go:** `clean` (round-trips byte-equivalent)

### `h8_decimal_attr`

_H8; extension types (decimal, ipaddr, datetime, duration)._

- **cedar-policy:** `clean` (round-trips byte-equivalent)
- **cedar-go:** `clean` (round-trips byte-equivalent)

### `h8b_ipaddr_attr`

_H8; extension types (decimal, ipaddr, datetime, duration)._

- **cedar-policy:** `clean` (round-trips byte-equivalent)
- **cedar-go:** `clean` (round-trips byte-equivalent)

### `h8c_datetime_and_duration_attrs`

_H8; extension types (decimal, ipaddr, datetime, duration)._

- **cedar-policy:** `clean` (round-trips byte-equivalent)
- **cedar-go:** `clean` (round-trips byte-equivalent)

### `h8d_extension_in_common_type`

_H8; extension types (decimal, ipaddr, datetime, duration)._

- **cedar-policy:** `clean` (round-trips byte-equivalent)
- **cedar-go:** `parse_fail`; `namespace "": entity "U" shape: attribute "bal": unknown type "Bal"`


## Phase A predicted vs found

The widening hypothesis was: cedar-go's schema marshaller has *multiple* AST variants its walker doesn't handle, and NEW-1 is one instance of an architectural class. The widened probe set covered 8 distinct hypothesis classes (H1-H8). After well-formedness filtering against `cedar check-parse`, the honest finding is **narrower than predicted**: every cedar-go silent-diff lives in the **entity-shape collapse** class. Specifically, the four well-formed cedar-go silent-diffs (`h1`, `h1b`, `h1c`, `h1d`) are all entity-shape ::= TypeRef-naming-a-common-type variants; cedar-go silently emits an empty Record for each, dropping the common-type alias.

The non-finding outcomes are themselves informative:

- H3/H4/H6b/H7/H8d: cedar-go's `unmarshalType` does not implement the bare-name TypeRef sugar (`{"type": "Foo"}`) in record-attribute / tags / context positions. It returns `unknown type "Foo"` honestly. **Feature gap, not a finding.**
- H1e (chained common types): same root cause as H3; cedar-go rejects bare-name TypeRefs even inside another common-type. Honest error.
- H2*: ill-formed JSON (entity shape != Record literal) per cedar-spec; excluded from findings.
- H5 / H7b / H8a-c: cedar-go round-trips cleanly. The marshaller correctly handles deep `in` chains, multi-action appliesTo, and inline extension types in record attrs.

**Architectural root cause of the H1 silent-diffs:** `cedar-go/x/exp/schema/ast/ast.go:55` defines `Entity.Shape` as `RecordType` (a type-erased map). The AST cannot represent any non-Record-literal shape, so the JSON unmarshaller in `internal/json/json.go:336` calls `unmarshalRecordType(jet.Shape)` *unconditionally*, ignoring `jet.Shape.Type`. When `jet.Shape.Type` is anything other than `Record` (e.g. a TypeRef naming a common type), the resulting `RecordType` is empty (no `attributes` to iterate). The Cedar-text marshaller then faithfully emits `entity Baz {};`. The fix requires widening the AST to admit TypeRef shapes, not just patching the marshaller.

## Goal-state assessment

- NEW-1 was 1 silent-diff. Phase I widening adds 3 more well-formed silent-diffs (h1b, h1c, h1d) in the same architectural class; common-type-with-optional-attr, namespaced common-type, EntityOrCommon-tagged TypeRef. Total: **4 well-formed cedar-go silent-diffs**, all in the entity-shape-TypeRef-collapse class.
- Predicted but NOT found: silent-diffs in deeper-nested (record-attr) common-type-refs, multi-namespace, tagged entities, action context. cedar-go honestly errors on these (feature gap, NOT a finding).
- Phase B Lean lift: triggered. The 4 silent-diffs cluster tightly around one well-formedness predicate (`shape resolves to a Record after common-type resolution`); this is exactly what `cedar-spec/cedar-lean/Cedar/Validation/Types.lean:118` requires. A Lean type-directed generator that outputs only well-formed (resolved-shape-is-Record) schemas is a soundness-preserving lift of the Phase A probe.

