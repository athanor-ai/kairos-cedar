/-
  CedarBridge.Predicates. Prop-valued predicates over cedar-spec's
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
  `isWellTypedWithCaps env c e`. same, with a caller-supplied starting
  capability set. Kept as a distinct predicate so later policies that
  check inside-a-conditional-arm typing can compose the capability
  threading Palamedes observes.
-/
public def isWellTypedWithCaps (env : TypeEnv) (c₀ : Capabilities) (e : Expr) : Prop :=
  ∃ te c, Cedar.Validation.typeOf e c₀ env = .ok (te, c)

/-- A well-typed expression wrapped in a subtype for generator outputs. -/
public abbrev WellTypedExpr (env : TypeEnv) := { e : Expr // isWellTyped env e }

/--
  `isWellFormedEnv env` holds when `env : TypeEnv` passes cedar-spec's
  structural-well-formedness checker. The checker walks the entity
  schema, action schema, and request-type components and rejects
  malformed attribute maps, dangling entity references, and
  cycle-inducing action relationships.

  Palamedes-style derivation target for a schema-level generator:
  `generator_search (fun env => isWellFormedEnv env)` yields random
  well-formed `TypeEnv`s that the bridge's other predicates can be
  conditioned on.
-/
public def isWellFormedEnv (env : TypeEnv) : Prop :=
  Cedar.Validation.TypeEnv.validateWellFormed env = .ok ()

/-- A well-formed environment wrapped in a subtype. -/
public abbrev WellFormedEnv := { env : TypeEnv // isWellFormedEnv env }

/--
  `isValidRequest schema request` holds when `request` matches at
  least one environment in `schema`. This is cedar-spec's notion of
  a request that the evaluator will dispatch (vs. one that fails the
  environment-match gate).

  Derivation target for a request-level generator:
  `generator_search (fun req => isValidRequest schema req)` yields
  random requests compatible with the given schema.
-/
public def isValidRequest (schema : Schema) (request : Request) : Prop :=
  Cedar.Validation.validateRequest schema request = .ok ()

/-- A schema-valid request wrapped in a subtype. -/
public abbrev ValidRequest (schema : Schema) :=
  { request : Request // isValidRequest schema request }

/--
  `areValidEntities schema entities` holds when every entity in
  `entities` has the shape its schema entry declares. This is the
  acceptance oracle for an entity-store generator.
-/
public def areValidEntities (schema : Schema) (entities : Entities) : Prop :=
  Cedar.Validation.validateEntities schema entities = .ok ()

/-- A schema-valid entity store wrapped in a subtype. -/
public abbrev ValidEntities (schema : Schema) :=
  { entities : Entities // areValidEntities schema entities }

end CedarBridge
