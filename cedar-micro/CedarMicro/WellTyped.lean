/-
  CedarMicro.WellTyped — the generator target.

  Defines a functional typechecker `getType : Expr → List Ty → Option Ty`
  in the Palamedes STLC-style (exactly matching
  `Palamedes/Examples/STLC/WellTyped/WellTyped.lean`), wraps it as a
  `Prop`-valued `isWellTyped` predicate, and invokes `generator_search`
  to synthesise the generator.

  Type rules (the only judgments `getType` honors):
    litInt n        : int   (always)
    litBool b       : bool  (always)
    var k           : Γ[k]  (lookup; fails if out of range)
    ite c t f       : τ     (if c : bool and t,f : τ matching)
    and a b         : bool  (if a,b : bool)

  If Palamedes's Aesop tactic closes this goal (via the Ty.as_or /
  Expr.as_or / deforest_eq lemmas scaffolded in Ty.lean + Expr.lean),
  we get a `Gen Expr` that produces expressions well-typed under Γ.
  That's the V1 milestone.
-/

import CedarMicro.Ty
import CedarMicro.Expr
import Palamedes.Synthesizer

open Gen CorrectGen

namespace CedarMicro

set_option maxHeartbeats 5000000

/-- Functional typechecker. Mirrors the STLC example's `getType`
    shape so Palamedes's recursion-scheme detection can match. -/
@[simp]
def getType (e : Expr) (Γ : List Ty) : Option Ty :=
  match e with
  | .litInt _  => pure .int
  | .litBool _ => pure .bool
  | .var n     => Γ[n]?
  | .ite c t f => do
    let τc ← getType c Γ
    let τt ← getType t Γ
    let τf ← getType f Γ
    guard (τc == Ty.bool)
    guard (τt == τf)
    pure τt
  | .and a b => do
    let τa ← getType a Γ
    let τb ← getType b Γ
    guard (τa == Ty.bool)
    guard (τb == Ty.bool)
    pure Ty.bool

/-- `isWellTyped Γ e` holds iff `getType e Γ` succeeds. This is the
    predicate Palamedes's `generator_search` inverts into a
    `Gen Expr`. -/
@[simp]
def isWellTyped (Γ : List Ty) (e : Expr) : Prop :=
  ∃ (τ : Ty), getType e Γ = τ

/-- Main V1 goal: Palamedes's Aesop tactic closes this. If Aesop
    replies "made no progress", the scaffolding in Ty.lean / Expr.lean
    needs more rules registered. -/
attribute [local simp] Ty.as_or Ty.deforest_eq Expr.as_or Expr.deforest_eq in
def genWellTyped (Γ : List Ty) : Gen Expr := by
  generator_search (fun e => isWellTyped Γ e)

end CedarMicro
