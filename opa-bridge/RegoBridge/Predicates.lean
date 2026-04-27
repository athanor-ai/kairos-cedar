/-
  RegoBridge.Predicates: Prop-valued predicates over the Rego subset,
  shaped so a generator-search can target them.

  Mirrors CedarBridge.Predicates in structure:
    - `isWellTypedRego σ e τ` wraps `HasType` for generator targeting
    - `WellTypedRegoExpr σ τ` is a subtype of well-typed expressions
    - `isWellTypedBool σ e` is the special case used by PolicyGen (τ = scalar bool)

  The typing relation `HasType` is an inductive Prop (not a decision procedure).
  For the generator, we use the constructive witnesses from HasType derivations
  directly.  A Boolean decision procedure `hasTypeDec` is provided as a
  companion for the diff runner's pre-filter step.
-/

import RegoBridge.Spec.Expr

namespace RegoBridge

open Rego.Spec

/--
  `isWellTypedRego σ e τ` holds when expression `e` is well-typed at type `τ`
  under schema `σ`.

  Shape matches the CedarBridge predicate: a direct wrapper around the inductive
  `HasType` relation.  A generator targeting this predicate produces only
  expressions the OPA type checker will accept under the given schema.
-/
def isWellTypedRego (σ : Schema) (e : Expr) (τ : RegoType) : Prop :=
  HasType σ e τ

/-- A well-typed expression at type `τ` wrapped in a subtype. -/
abbrev WellTypedRegoExpr (σ : Schema) (τ : RegoType) :=
  { e : Expr // isWellTypedRego σ e τ }

/-- The special case used by the PolicyGen: a well-typed boolean expression. -/
def isWellTypedBool (σ : Schema) (e : Expr) : Prop :=
  HasType σ e (.scalar .bool)

/-- A well-typed boolean expression wrapped in a subtype. -/
abbrev WellTypedBoolExpr (σ : Schema) :=
  { e : Expr // isWellTypedBool σ e }

/-── Decision procedure ──────────────────────────────────────────────────────-/

/-- Infer the type of an expression under the schema (separated for mutual use).
    Returns `none` if the type cannot be determined. -/
def inferType (σ : Schema) : Expr → Option RegoType
  | .lit (.bool _)   => some (.scalar .bool)
  | .lit (.number _) => some (.scalar .number)
  | .lit (.string _) => some (.scalar .string)
  | .lit .null       => some (.scalar .null)
  | .input_attr key  =>
    match σ.lookup key with
    | some τ => some τ
    | none   => some .any_
  | .nested key sub  =>
    match σ.lookup key with
    | some (.object fs) =>
      match (fs.find? (fun (k, _) => k == sub)).map (·.2) with
      | some τ => some τ
      | none   => some .any_
    | _ => some .any_
  | .cmp _ _ _      => some (.scalar .bool)
  | .in_set _ _     => some (.scalar .bool)
  | .in_arr _ _     => some (.scalar .bool)
  | .and_ _ _       => some (.scalar .bool)
  | .or_ _ _        => some (.scalar .bool)
  | .not_ _         => some (.scalar .bool)

/-- A Boolean decision procedure for `HasType` (conservative approximation).
    Returns `true` when `HasType` definitely holds; may return `false` for
    some valid derivations involving `any_` in complex positions.  Used as a
    pre-filter in the diff runner so generated policies are always well-typed
    according to the static checker.

    This is the analogue of `CedarBridge.wellTypedAt`. -/
def hasTypeDec (σ : Schema) : Expr → RegoType → Bool
  | .lit (.bool _),   .scalar .bool   => true
  | .lit (.number _), .scalar .number => true
  | .lit (.string _), .scalar .string => true
  | .lit .null,       .scalar .null   => true
  | .lit _,           _               => false

  | .input_attr key, τ =>
    match σ.lookup key with
    | some τ' => (τ' == τ)
    | none    => (τ == .any_)

  | .nested key sub, τ =>
    match σ.lookup key with
    | some (.object fs) =>
      match (fs.find? (fun (k, _) => k == sub)).map (·.2) with
      | some τ' => (τ' == τ)
      | none    => (τ == .any_)
    | _ => (τ == .any_)

  | .cmp _ e1 e2, .scalar .bool =>
    -- Accept if both sides infer the same type, or if either is any_
    let τ1 := inferType σ e1
    let τ2 := inferType σ e2
    match τ1, τ2 with
    | some .any_, _ | _, some .any_ => true
    | some τ1', some τ2'            => (τ1' == τ2')
    | none, _ | _, none             => false
  | .cmp _ _ _, _ => false

  | .in_set e vs, .scalar .bool =>
    -- Any non-none inferred type is acceptable on the left; set must be non-empty
    (inferType σ e).isSome && !vs.isEmpty
  | .in_set _ _, _ => false

  | .in_arr key e2, .scalar .bool =>
    match σ.lookup key with
    | some (.array elemTy) => hasTypeDec σ e2 elemTy
    | _ => false
  | .in_arr _ _, _ => false

  | .and_ e1 e2, .scalar .bool =>
    hasTypeDec σ e1 (.scalar .bool) && hasTypeDec σ e2 (.scalar .bool)
  | .and_ _ _, _ => false

  | .or_ e1 e2, .scalar .bool =>
    hasTypeDec σ e1 (.scalar .bool) && hasTypeDec σ e2 (.scalar .bool)
  | .or_ _ _, _ => false

  | .not_ e, .scalar .bool =>
    hasTypeDec σ e (.scalar .bool)
  | .not_ _, _ => false

/-- `isWellTypedBoolDec σ e` holds when `hasTypeDec σ e (.scalar .bool) = true`. -/
def isWellTypedBoolDec (σ : Schema) (e : Expr) : Bool :=
  hasTypeDec σ e (.scalar .bool)

end RegoBridge
