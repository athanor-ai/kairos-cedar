# Phase I: Entity-Store + Schema-Marshaller Bug Hunt

Date: 2026-04-26
Agent: platform (entity-store + schema-marshaller surface)
Tools: cedar-policy (Rust) 4.10.0 vs cedar-go (Go) 1.6.0

## Surfaces tested

Schema JSON marshaller: cedar-go/x/exp/schema/internal/json/json.go,
  cedar-go/x/exp/schema/internal/parser/marshal.go, cedar-go/x/exp/schema/ast/types.go
Entity-store JSON: cedar-go/types/datetime.go, cedar-go/types/json.go,
  cedar-go/types/entity_map.go

## Disagreements found: 2

### B-I1: Schema JSON parse incompatibility

Severity: hard parse error on valid Rust-emitted schema JSON.

cedar-go unmarshalType (x/exp/schema/internal/json/json.go:395-423) handles only known
type keywords. Rust emits CommonTypeRef as {"type": "Address"} (bare name as type field).
cedar-go returns: unknown type "Address". Any schema JSON from Rust using commonTypes
with entity attr references fails to parse in cedar-go.

Classification: New class -- schema-marshaller parse incompatibility.
See: disagreements/B-I1_schema_json_commontype_parse/CANONICAL_REPRO.md

### B-I2: datetime wire-format normalization (B0-extension)

Severity: wire-format divergence only, NOT a policy-decision divergence.

cedar-go Datetime.String() (types/datetime.go:270-276) always emits .000 milliseconds.
MarshalJSON() calls String() so this leaks into wire JSON.

Input "2024-01-15T00:00:00Z" -> Go "2024-01-15T00:00:00.000Z" / Rust preserves original.
Input "2024-01-15T00:00:00.123Z" -> both preserve (already has ms component).

Classification: B0-extension (same normalisation class as ip and decimal).
See: disagreements/B-I2_datetime_wire_normalization/CANONICAL_REPRO.md

## Null findings

Cedar-text schema round-trips: stable in cedar-go.
Primitive type names as EntityOrCommon: both impls emit same form, not cedar-go bug.
Cross-namespace refs: stable. Entity tags w/ common type: stable.
Implicit entity UID in attr value: both parse as Record (agreement).
Deeply nested records: round-trip stable.
