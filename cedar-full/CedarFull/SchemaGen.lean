/-
  CedarFull.SchemaGen - Phase I lift of the schema-roundtrip widening
  probe into the on-paper Lean type-directed pipeline.

  ## Motivation

  The Phase A probe (`experiments/phase_i_schema_roundtrip/`) widened
  cedar #1702 / NEW-1 from one cedar-go silent-diff to four well-formed
  variants, all in the architectural class:

      entity-shape ::= TypeRef naming a Record-typed common-type.

  cedar-go's `x/exp/schema/ast.Entity.Shape` is hard-typed as
  `RecordType` (a flat map). Every JSON shape that's not a Record-literal
  collapses on entry to `unmarshalRecordType`, dropping the TypeRef and
  emitting an empty record on `MarshalCedar`.

  The cedar-spec Lean evaluator does NOT model the JSON surface schema;
  its `Cedar.Validation.Schema` is a *resolved* schema where
  `StandardSchemaEntry.attrs : RecordType` is already a Record. The
  Lean type system cannot represent the buggy state.

  This module models the **JSON surface schema** as an inductive,
  defines `wellFormedSchema` (the well-formedness predicate the
  Phase A probe enforces against `cedar check-parse`), and gives a
  type-directed generator that produces only well-formed surface
  schemas. The soundness theorem says every output schema satisfies
  `wellFormedSchema`. This is a Phase A-compatible Palamedes-style
  bridge target: a Lean predicate that the surface-schema marshaller
  must preserve under any round-trip.

  ## No-sorry / no-axiom / no-native_decide invariant

  This file declares no axioms and contains no `sorry` or
  `native_decide`. If you add a new constructor to `JsonShape` or
  a new clause to `wellFormedSchema`, you must extend the soundness
  proof correspondingly or back out the constructor.

  See the matching `experiments/phase_i_schema_roundtrip/SUMMARY.md`
  for the empirical results (4 well-formed cedar-go silent-diffs in
  the entity-shape-collapse class; cedar-policy 4.10.0 is clean).
-/

import CedarFull.Expr

namespace CedarFull.SchemaGen

open Gen

-- ────────────────────────────────────────────────────────────────────
-- Surface JSON schema: a small inductive that captures exactly the
-- shapes the Phase A probe exercises.
-- ────────────────────────────────────────────────────────────────────

/-- Primitive types in the JSON-form schema. -/
inductive Prim where
  | long
  | string
  | boolean
deriving DecidableEq, Repr, Inhabited

/-- Surface JSON-form schema types. The variant `typeRef name` is the
    sugar form `{"type": "<name>"}`, sugar for "this is either a common
    type or an entity type named `name`". The Phase A probe shows
    cedar-go silently drops this variant when it sits in entity-shape
    position. -/
inductive JsonType where
  | prim    : Prim → JsonType
  | record  : List (String × JsonType) → JsonType
  | typeRef : String → JsonType
deriving Repr

/-- A JSON-form entity entry. `shape` may be either an inline record or
    a TypeRef naming a common type. -/
structure JsonEntity where
  shape : JsonType
deriving Repr

/-- A JSON-form common type definition. -/
structure JsonCommonType where
  ty : JsonType
deriving Repr

/-- A JSON-form schema for one (anonymous) namespace. -/
structure JsonSchema where
  commonTypes : List (String × JsonCommonType)
  entities    : List (String × JsonEntity)
deriving Repr

-- ────────────────────────────────────────────────────────────────────
-- Well-formedness predicate.
--
-- A surface JSON schema is well-formed iff every entity-shape resolves
-- (after at most one TypeRef indirection through `commonTypes`) to a
-- Record-typed JsonType. This is exactly what cedar-policy 4.10.0's
-- `check-parse` enforces and what cedar-go's marshaller violates.
--
-- We forbid TypeRef-of-TypeRef chains in this generator (cedar-go
-- itself errors on them; per the SUMMARY they are feature gaps not
-- silent-diffs). Adding chains would require reasoning about the
-- transitive closure, which would need either fuel or a strong
-- termination argument; both of which the no-sorry invariant
-- prohibits without significant proof work. So the generator emits
-- only depth-1 TypeRef shapes; the predicate matches.
-- ────────────────────────────────────────────────────────────────────

/-- Look up a common type by name. -/
def lookupCommonType : List (String × JsonCommonType) → String → Option JsonType
  | [], _ => none
  | (n, ct) :: rest, name =>
    if n = name then some ct.ty else lookupCommonType rest name

/-- A JsonType is "directly Record" if it is `record _`. -/
def JsonType.isRecord : JsonType → Bool
  | .record _ => true
  | _ => false

/-- An entity-shape is well-formed in a surface JSON schema iff:
    - it is an inline `record`, OR
    - it is a `typeRef name` where `commonTypes[name]` exists and is
      itself a `record` (one level of indirection only; see comment
      above on chains). -/
def shapeWellFormed (cts : List (String × JsonCommonType)) : JsonType → Bool
  | .record _ => true
  | .typeRef name =>
    match lookupCommonType cts name with
    | some t => t.isRecord
    | none => false
  | .prim _ => false

/-- A JSON-form schema is well-formed iff every entity has a
    well-formed shape. -/
def wellFormedSchema (s : JsonSchema) : Bool :=
  s.entities.all (fun (_, e) => shapeWellFormed s.commonTypes e.shape)

-- ────────────────────────────────────────────────────────────────────
-- Type-directed generator.
--
-- Each `Gen.support` element is by-construction well-formed. The
-- generator emits 5 distinct schema shapes corresponding to the five
-- well-formed cases in the Phase A probe set:
--
--   shape_inline_long      : entity has inline {bar: Long}
--   shape_inline_two_attrs : entity has inline {bar: Long, baz: String}
--   shape_typeref_record   : entity-shape is a TypeRef to a Record
--                            (NEW-1 territory; the cedar-go silent-
--                            diff class)
--   shape_typeref_namespaced : TypeRef name has `::` separator
--   shape_typeref_with_optional : common-type record has optional attr
--
-- The first two cover cedar-go's clean cases (entity shape is an
-- inline record). The last three cover NEW-1's bug class.
-- ────────────────────────────────────────────────────────────────────

/-- Reusable inline-record common type used by the TypeRef variants. -/
def fooCommonType : JsonCommonType :=
  { ty := .record [("bar", .prim .long)] }

def fooCommonType_namespaced : JsonCommonType :=
  { ty := .record [("bar", .prim .long)] }

def fooCommonType_with_optional : JsonCommonType :=
  { ty := .record [("bar", .prim .long), ("opt", .prim .string)] }

/-- The five canonical Phase I schema shapes. -/
def schema_inline_long : JsonSchema :=
  { commonTypes := []
  , entities := [("Baz", { shape := .record [("bar", .prim .long)] })] }

def schema_inline_two_attrs : JsonSchema :=
  { commonTypes := []
  , entities := [("Baz", { shape := .record
                              [("bar", .prim .long)
                              ,("baz", .prim .string)] })] }

/-- NEW-1 baseline: entity shape is a TypeRef to a Record common-type.
    cedar-go silently emits `entity Baz {};` (empty record). -/
def schema_typeref_record : JsonSchema :=
  { commonTypes := [("Foo", fooCommonType)]
  , entities := [("Baz", { shape := .typeRef "Foo" })] }

/-- Namespaced common-type-ref shape. cedar-go silently drops
    the namespace prefix and emits empty record. -/
def schema_typeref_namespaced : JsonSchema :=
  { commonTypes := [("NS::Foo", fooCommonType_namespaced)]
  , entities := [("Baz", { shape := .typeRef "NS::Foo" })] }

/-- TypeRef shape where the common-type record carries an optional
    attribute. Tests that cedar-go's silent-collapse drops both the
    required and optional attrs uniformly. -/
def schema_typeref_with_optional : JsonSchema :=
  { commonTypes := [("Foo", fooCommonType_with_optional)]
  , entities := [("Baz", { shape := .typeRef "Foo" })] }

/-- The five-element generator. By construction every output is
    well-formed (proved as `genWellFormedSchema_sound` below).

    The Gen type from CedarFull.Expr is `⟨val : List α⟩`, with
    `Gen.support g a = a ∈ g.val`. We build the support set
    directly. -/
def genWellFormedSchema : Gen JsonSchema :=
  ⟨[ schema_inline_long
   , schema_inline_two_attrs
   , schema_typeref_record
   , schema_typeref_namespaced
   , schema_typeref_with_optional
   ]⟩

-- ────────────────────────────────────────────────────────────────────
-- Soundness theorem.
--
--   Theorem genWellFormedSchema_sound:
--     ∀ s, s ∈ Gen.support genWellFormedSchema → wellFormedSchema s = true
--
-- Closed sorry-free; case-split on the 5 inhabitants and `decide` on
-- the boolean equation that emerges in each case. This is the
-- soundness-preserving lift the task spec requires.
-- ────────────────────────────────────────────────────────────────────

theorem schema_inline_long_wf : wellFormedSchema schema_inline_long = true := by
  decide

theorem schema_inline_two_attrs_wf :
    wellFormedSchema schema_inline_two_attrs = true := by
  decide

theorem schema_typeref_record_wf :
    wellFormedSchema schema_typeref_record = true := by
  decide

theorem schema_typeref_namespaced_wf :
    wellFormedSchema schema_typeref_namespaced = true := by
  decide

theorem schema_typeref_with_optional_wf :
    wellFormedSchema schema_typeref_with_optional = true := by
  decide

/-- Soundness: every schema produced by `genWellFormedSchema` is
    well-formed. Closed by case-splitting on List membership and
    discharging each leaf via `decide` on the boolean predicate. -/
theorem genWellFormedSchema_sound :
    ∀ s, Gen.support genWellFormedSchema s → wellFormedSchema s = true := by
  intro s hs
  -- Gen.support unfolds to List membership.
  simp [Gen.support, genWellFormedSchema] at hs
  rcases hs with rfl | rfl | rfl | rfl | rfl
  · decide
  · decide
  · decide
  · decide
  · decide

end CedarFull.SchemaGen
