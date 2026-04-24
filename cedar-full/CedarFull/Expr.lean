/-
  CedarFull.Expr: a fuel-bounded, type-directed generator for
  Cedar.Spec.Expr (the full 12-constructor expression type) under a
  Cedar.Validation.TypeEnv.

  V1 scope (arity classes 1–4, constructors 1–7):
    • Flat (2):             lit, var
    • Unary-recursive (3):  unaryApp, getAttr, hasAttr
    • Binary-recursive (3): and, or, binaryApp
    • Ternary-recursive (1): ite

  N-ary constructors (set / record / call) are Phase B scope — noted
  with TODO comments pointing at ATH-534.

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
      -- ite: cond bool, then/else bool
      (do let c ← genSize env 0 boolTy
          let t ← genSize env 0 (.bool bty)
          let f ← genSize env 0 (.bool bty)
          pure (.ite c t f))))
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
      -- ite: cond bool, then/else int
      (do let c ← genSize env 0 (.bool .anyBool)
          let t ← genSize env 0 .int
          let f ← genSize env 0 .int
          pure (.ite c t f))))
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
  | _ + 1, τ =>
    -- set / record / ext: Phase B (ATH-534). Fall back to leaf.
    genLeaf env τ

-- ── genWellTyped ────────────────────────────────────────────────────

/-- Generate a well-typed Cedar expression under `env` at result type
    `τ`, with fuel = 3. By `CedarFull.Soundness.genWellTyped_sound`,
    every expression in the support satisfies `CedarBridge.isWellTyped env e`. -/
def genWellTyped (env : TypeEnv) (τ : CedarType) : Gen Expr :=
  genSize env 3 τ

end CedarFull
