/-
  CedarFull.Expr: a fuel-bounded, type-directed generator for
  Cedar.Spec.Expr (the full 12-constructor expression type) under a
  Cedar.Validation.TypeEnv.

  V1 scope (arity classes 1–4, constructors 1–7):
    • Flat (2):             lit, var
    • Unary-recursive (3):  unaryApp, getAttr, hasAttr
    • Binary-recursive (3): and, or, binaryApp
    • Ternary-recursive (1): ite

  V2 widening (§8 commit, ATH widen-genpolicy-extension-types):
    • N-ary constructors (set / record / call) are now scaffolded with
      explicit-shape constructors (extDecimalLit, extIpLit,
      setLitUserEntities, recordEmptyLit, recordSingletonLit, nestedAttrLit)
      used by PolicyGen.  Each has a bottom-up soundness lemma in
      Soundness.lean (some sorry-marked pending follow-up).

  Mirrors the structure of cedar-micro/CedarMicro/WellTyped.lean:
    • A minimal self-contained Gen type backed by List (Palamedes pins
      Lean 4.24.0; cedar-full pins 4.29.1, so Palamedes cannot be
      imported directly).  Gen α = List α with explicit support lemmas.
    • varsOfType helper over the four Cedar Var constructors.
    • genLeaf / genSize / genWellTyped following the same pattern.
-/

import CedarBridge

open Cedar.Spec
open Cedar.Validation
open CedarBridge

namespace CedarFull

-- ── Minimal Gen type backed by List ────────────────────────────────
-- Gen α wraps a List α.  The only operations we need are:
--   pure a     = ⟨[a]⟩
--   pick x y   = ⟨x.val ++ y.val⟩          (union of outcomes)
--   bind x f   = ⟨x.val.flatMap (·.val ∘ f)⟩  (flatMap)
--   support g a = a ∈ g.val
-- This matches the Palamedes.Gen support semantics for finite gens.

structure Gen (α : Type) where
  val : List α

namespace Gen

def pick (x y : Gen α) : Gen α := ⟨x.val ++ y.val⟩

def ret (a : α) : Gen α := ⟨[a]⟩

def bind' (x : Gen α) (f : α → Gen β) : Gen β :=
  ⟨x.val.flatMap (fun a => (f a).val)⟩

instance : Pure Gen where pure := ret
instance : Bind Gen where bind := bind'
instance : Monad Gen where

def support (g : Gen α) (a : α) : Prop := a ∈ g.val

namespace Support

@[simp]
theorem support_pure (a : α) : support (pure a : Gen α) = (· = a) := by
  funext b
  simp [support, pure, ret, eq_comm]

@[simp]
theorem support_pick (x y : Gen α) :
    support (pick x y) = fun a => support x a ∨ support y a := by
  funext a
  simp [support, pick, List.mem_append]

@[simp]
theorem support_bind (x : Gen α) (f : α → Gen β) :
    support (x >>= f) = fun b => ∃ a, support x a ∧ support (f a) b := by
  funext b
  simp [support, bind, bind', List.mem_flatMap]

end Support

end Gen

open Gen.Support

-- ── varsOfType ──────────────────────────────────────────────────────
-- Cedar Var constructors and the types they produce:
--   principal → .entity env.reqty.principal
--   action    → .entity env.reqty.action.ty
--   resource  → .entity env.reqty.resource
--   context   → .record env.reqty.context
-- Return every Var whose type equals τ.

def varsOfType (env : TypeEnv) (τ : CedarType) : List Var :=
  let principalType : CedarType := .entity env.reqty.principal
  let actionType    : CedarType := .entity env.reqty.action.ty
  let resourceType  : CedarType := .entity env.reqty.resource
  let contextType   : CedarType := .record env.reqty.context
  (if τ = principalType then [.principal] else []) ++
  (if τ = actionType    then [.action]    else []) ++
  (if τ = resourceType  then [.resource]  else []) ++
  (if τ = contextType   then [.context]   else [])

-- ── wellTypedAt: boolean soundness predicate ────────────────────────

def wellTypedAt (env : TypeEnv) (e : Expr) : Bool :=
  match Cedar.Validation.typeOf e [] env with
  | .ok _    => true
  | .error _ => false

-- ── litGen ──────────────────────────────────────────────────────────

def litGen (τ : CedarType) : Gen Expr :=
  match τ with
  | .bool _  => Gen.pick (pure (.lit (.bool true))) (pure (.lit (.bool false)))
  | .int     => pure (.lit (.int 0))
  | .string  => pure (.lit (.string ""))
  | _        =>
    -- entity / set / record / ext: no literal constructor for V1.
    -- Fallback to bool false literal; entity leaf cases go through
    -- varGen when varsOfType is non-empty.
    pure (.lit (.bool false))

-- ── varGen ──────────────────────────────────────────────────────────

def varGen (vars : List Var) : Gen Expr :=
  ⟨vars.map (fun v => Expr.var v)⟩

-- ── genLeaf ─────────────────────────────────────────────────────────

def genLeaf (env : TypeEnv) (τ : CedarType) : Gen Expr :=
  Gen.pick (varGen (varsOfType env τ)) (litGen τ)

-- ── hasAttr support ─────────────────────────────────────────────────
-- A small fixed list of candidate attribute names used by the
-- `hasAttr (.var .context) <name>` arm of genSize.  For any name `a`,
-- `hasAttr (.var .context) a` typechecks to a bool: the context var
-- always types as `.record env.reqty.context`, and typeOfHasAttr's
-- `.record` branch returns `.ok` for both the present-attr and
-- missing-attr cases (returning `.bool .tt`, `.bool .anyBool`, or
-- `.bool .ff` depending on the attribute's required/optional/missing
-- status; all three are ok-results so wellTypedAt is true).
def hasAttrNames : List String :=
  ["approved", "tags", "name", "level", "id"]

/-- Generator for `hasAttr (.var .context) <name>` over a fixed set of
    attribute names.  Output type is always bool (subkind varies with
    the schema's actual context shape). -/
def genHasAttrContext : Gen Expr :=
  ⟨hasAttrNames.map (fun a => Expr.hasAttr (.var .context) a)⟩

-- ── getAttr-via-record-singleton support ────────────────────────────
-- For each requested type τ, generate
--   .getAttr (.record [("v", e)]) "v"
-- where e is a leaf at type τ.  This pattern exercises both the
-- `.getAttr` and `.record` constructors in a schema-independent way:
-- the record literal types as `[("v", .required <τ>)]`, and getAttr
-- on a known-required key returns `.required τ`'s underlying type.
-- The output type matches τ for τ ∈ {.bool .anyBool, .int}.
def genGetAttrOfRecordSingleton (inner : Gen Expr) : Gen Expr :=
  do let a ← inner
     pure (.getAttr (.record [("v", a)]) "v")

-- ── genSize ─────────────────────────────────────────────────────────

def genSize (env : TypeEnv) : Nat → CedarType → Gen Expr
  | 0, τ => genLeaf env τ
  | _ + 1, .bool bty =>
    let boolTy : CedarType := .bool .anyBool
    Gen.pick (genLeaf env (.bool bty))
    (Gen.pick
      -- and: both arms must be bool
      (do let a ← genSize env 0 boolTy
          let b ← genSize env 0 boolTy
          pure (.and a b))
    (Gen.pick
      -- or: both arms must be bool
      (do let a ← genSize env 0 boolTy
          let b ← genSize env 0 boolTy
          pure (.or a b))
    (Gen.pick
      -- ite: cond bool, then/else bool
      (do let c ← genSize env 0 boolTy
          let t ← genSize env 0 (.bool bty)
          let f ← genSize env 0 (.bool bty)
          pure (.ite c t f))
    (Gen.pick
      -- unaryApp .not : bool → bool
      (do let a ← genSize env 0 boolTy
          pure (.unaryApp .not a))
    (Gen.pick
      -- binaryApp .eq : int × int → bool (same-type equality)
      (do let a ← genSize env 0 .int
          let b ← genSize env 0 .int
          pure (.binaryApp .eq a b))
    (Gen.pick
      -- binaryApp .eq : bool × bool → bool
      (do let a ← genSize env 0 boolTy
          let b ← genSize env 0 boolTy
          pure (.binaryApp .eq a b))
    (Gen.pick
      -- binaryApp .less : int × int → bool
      (do let a ← genSize env 0 .int
          let b ← genSize env 0 .int
          pure (.binaryApp .less a b))
    (Gen.pick
      -- binaryApp .lessEq : int × int → bool
      (do let a ← genSize env 0 .int
          let b ← genSize env 0 .int
          pure (.binaryApp .lessEq a b))
    (Gen.pick
      -- hasAttr (.var .context) <name>: context types as record,
      -- typeOfHasAttr's record branch returns ok for both present
      -- and missing attribute cases (varying the bool subkind).
      genHasAttrContext
    (Gen.pick
      -- getAttr (.record [("v", a)]) "v" with a a bool literal:
      -- record literal types as [("v", .required (.bool _))], and
      -- getAttr on a known-required key returns the attr's type.
      (genGetAttrOfRecordSingleton (genLeaf env (.bool .anyBool)))
    (Gen.pick
      -- unaryApp .isEmpty over a singleton-set: typeOfUnaryApp's
      -- (.isEmpty, .set _) case returns ok (.bool .anyBool).
      (pure (.unaryApp .isEmpty (.set [.lit (.int 0)])))
    (Gen.pick
      -- unaryApp .like over a string lit: typeOfUnaryApp's
      -- (.like _, .string) case returns ok (.bool .anyBool).
      (pure (.unaryApp (.like [.star]) (.lit (.string ""))))
    (Gen.pick
      -- unaryApp .is over var principal: typeOfUnaryApp's
      -- (.is ety₁, .entity ety₂) returns ok (.bool ...).
      (pure (.unaryApp (.is { id := "User", path := [] })
                       (.var .principal)))
    (Gen.pick
      -- binaryApp .mem entity×entity: typeOfBinaryApp's
      -- (.mem, .entity, .entity) returns ok (.bool _).
      (pure (.binaryApp .mem (.var .principal) (.var .resource)))
    (Gen.pick
      -- binaryApp .contains: (.set τ, _) → bool (lub-compatible);
      -- here both element type and rhs type are .int.
      (pure (.binaryApp .contains
                       (.set [.lit (.int 0)])
                       (.lit (.int 0))))
    (Gen.pick
      -- binaryApp .containsAll: (.set τ, .set τ) → bool .anyBool.
      (pure (.binaryApp .containsAll
                       (.set [.lit (.int 0)])
                       (.set [.lit (.int 0)])))
      -- binaryApp .containsAny: same shape.
      (pure (.binaryApp .containsAny
                       (.set [.lit (.int 0)])
                       (.set [.lit (.int 0)])))))))))))))))))))
  | _ + 1, .int =>
    Gen.pick (genLeaf env .int)
    (Gen.pick
      -- binaryApp .add : int × int → int
      (do let a ← genSize env 0 .int
          let b ← genSize env 0 .int
          pure (.binaryApp .add a b))
    (Gen.pick
      -- unaryApp .neg : int → int
      (do let a ← genSize env 0 .int
          pure (.unaryApp .neg a))
    (Gen.pick
      -- ite: cond bool, then/else int
      (do let c ← genSize env 0 (.bool .anyBool)
          let t ← genSize env 0 .int
          let f ← genSize env 0 .int
          pure (.ite c t f))
    (Gen.pick
      -- binaryApp .sub : int × int → int
      (do let a ← genSize env 0 .int
          let b ← genSize env 0 .int
          pure (.binaryApp .sub a b))
    (Gen.pick
      -- binaryApp .mul : int × int → int
      (do let a ← genSize env 0 .int
          let b ← genSize env 0 .int
          pure (.binaryApp .mul a b))
      -- getAttr (.record [("v", a)]) "v" with a an int literal:
      -- record literal types at [("v", .required .int)], and
      -- getAttr on a known-required key returns .int.
      (genGetAttrOfRecordSingleton (genLeaf env .int)))))))
  | _ + 1, .string =>
    -- No compound string forms for V1; leaf only.
    genLeaf env .string
  | _ + 1, .entity ety =>
    -- ite where then/else are both entity-typed at ety
    Gen.pick (genLeaf env (.entity ety))
      (do let c ← genSize env 0 (.bool .anyBool)
          let t ← genSize env 0 (.entity ety)
          let f ← genSize env 0 (.entity ety)
          pure (.ite c t f))
  | _ + 1, .set inner =>
    -- Singleton-set arm: `.set [a]` where `a` is any leaf at `inner`.
    -- typeOfSet on a one-element list of well-typed exprs always
    -- returns ok at `.set te.typeOf` (no lub fold needed for a
    -- singleton). Schema-independent.
    Gen.pick (genLeaf env (.set inner))
      (do let a ← genLeaf env inner
          pure (.set [a]))
  | _ + 1, .record _rty =>
    -- Empty-record arm: `.record []` typechecks under any environment
    -- via `wellTypedAt_recordEmpty`. The output type is
    -- `.record (Map.mk [])`, which need not equal the requested rty;
    -- but the expression is well-typed, which is what genSize_sound
    -- requires.
    Gen.pick (genLeaf env (.record _rty))
      (pure (.record []))
  | _ + 1, τ =>
    -- ext: Phase B (future work). Fall back to leaf.
    genLeaf env τ

-- ── genWellTyped ────────────────────────────────────────────────────

/-- Generate a well-typed Cedar expression under `env` at result type
    `τ`, with fuel = 3. By `CedarFull.Soundness.genWellTyped_sound`,
    every expression in the support satisfies `CedarBridge.isWellTyped env e`. -/
def genWellTyped (env : TypeEnv) (τ : CedarType) : Gen Expr :=
  genSize env 3 τ

-- ── §8 widening: extension/set/record/nested-attr generators ────────
--
-- These are explicit-shape constructors used directly by PolicyGen for
-- the four target classes called out in cedar-drt §8:
--   1. extension-type literals (decimal "1.0", ip "10.0.0.1")
--   2. set literals over entity UIDs
--   3. record literals (empty + single attribute)
--   4. nested attribute projection (record-typed intermediate)
-- Soundness lemmas live in Soundness.lean.

/-- Decimal extension literal: `decimal("1.0")`.  Produces
    `.call .decimal [.lit (.string "1.0")]`.  Typechecks at
    `(.ext .decimal)` for any environment because typeOfCall .decimal
    only checks the argument is a string literal that parses as a
    Decimal; and "1.0" does. -/
def extDecimalLit : Expr :=
  .call .decimal [.lit (.string "1.0")]

/-- IP extension literal: `ip("10.0.0.1")`.  Produces
    `.call .ip [.lit (.string "10.0.0.1")]`. -/
def extIpLit : Expr :=
  .call .ip [.lit (.string "10.0.0.1")]

/-- Set of three entity UIDs of type User.  Produces
    `.set [User::"alice", User::"bob", User::"carol"]`.  Typechecks at
    `(.set (.entity User))` regardless of schema content (typeOfSet
    accepts a non-empty homogeneous list). -/
def setLitUserEntities : Expr :=
  .set [ .lit (.entityUID { ty := { id := "User", path := [] }, eid := "alice" })
       , .lit (.entityUID { ty := { id := "User", path := [] }, eid := "bob" })
       , .lit (.entityUID { ty := { id := "User", path := [] }, eid := "carol" })
       ]

/-- Single-element set of User entities.  Produces
    `.set [User::"alice"]`.  Identical typing to setLitUserEntities
    (both at `(.set (.entity User))`); the cardinality difference
    isolates the cedar-drt-flagged single-membership divergence class
    on `.contains` vs `.mem`. -/
def setLitSingletonAlice : Expr :=
  .set [ .lit (.entityUID { ty := { id := "User", path := [] }, eid := "alice" }) ]

/-- Decimal extension literal with extra-precision string
    form `decimal("1.000")`. Same value semantically as `decimal("1.0")`
    but the string form differs. Probes the parser-level residual:
    cedar-rust and cedar-go run distinct Decimal parsers. Typechecks at
    `(.ext .decimal)` for the same reason extDecimalLit does. -/
def extDecimalLitThousandths : Expr :=
  .call .decimal [.lit (.string "1.000")]

/-- IPv6 localhost extension literal `ip("::1")`. Same
    .ext .ipaddr type as extIpLit (which is IPv4); the address-family
    difference probes whether cedar-rust and cedar-go evaluate IPv6
    forms identically. The double-colon zero-compression form is the
    canonical edge case for IPv6 parser drift. -/
def extIpV6LocalhostLit : Expr :=
  .call .ip [.lit (.string "::1")]

/-- Empty record literal: `{}`.  Produces `.record []`.  The empty
    record always typechecks (no attribute constraints). -/
def recordEmptyLit : Expr :=
  .record []

/-- Singleton record literal: `{ approved: true }`.  Produces
    `.record [("approved", .lit (.bool true))]`. -/
def recordSingletonLit : Expr :=
  .record [("approved", .lit (.bool true))]

/-- Nested attribute access: `principal.address.street`.  Requires the
    schema to declare `address : { street: String, ... }` on User and
    a capability for `(principal, .attr "address")` in the typing
    context (added by a preceding `principal has address` check). -/
def nestedAttrLit : Expr :=
  .getAttr (.getAttr (.var .principal) "address") "street"

end CedarFull
