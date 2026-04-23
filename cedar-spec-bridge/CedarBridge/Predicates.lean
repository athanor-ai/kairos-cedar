/-
  CedarBridge.Predicates — Prop-valued predicates over cedar-spec's
  def-based Cedar.Validation.typeOf, shaped so a Palamedes-style
  generator_search can target them.

  The cedar-spec typechecker is a functional def returning
  `Except TypeError (TypedExpr × Capabilities)`. Palamedes (and the
  generic derive-from-inductive-relation technique) wants a Prop
  predicate on the input. We supply the bridge here, keeping
  cedar-spec itself unmodified.
-/
module

public import Cedar.Spec
public import Cedar.Validation

namespace CedarBridge

open Cedar.Spec
open Cedar.Validation

/--
  `isWellTyped env e` holds when cedar-spec's `typeOf` accepts `e`
  under the empty capability set in environment `env`.

  Shape matches Palamedes examples: a ∃ over the derivation witnesses
  (`TypedExpr` and the output `Capabilities`) composed with an
  equality on the functional checker. A Palamedes-style
  `generator_search (fun e => isWellTyped env e)` inverts this
  predicate to produce expressions that the checker accepts.
-/
public def isWellTyped (env : TypeEnv) (e : Expr) : Prop :=
  ∃ te c, Cedar.Validation.typeOf e [] env = .ok (te, c)

/--
  `isWellTypedWithCaps env c e` — same, with a caller-supplied starting
  capability set. Kept as a distinct predicate so later policies that
  check inside-a-conditional-arm typing can compose the capability
  threading Palamedes observes.
-/
public def isWellTypedWithCaps (env : TypeEnv) (c₀ : Capabilities) (e : Expr) : Prop :=
  ∃ te c, Cedar.Validation.typeOf e c₀ env = .ok (te, c)

/-- A well-typed expression wrapped in a subtype for generator outputs. -/
public abbrev WellTypedExpr (env : TypeEnv) := { e : Expr // isWellTyped env e }

end CedarBridge
