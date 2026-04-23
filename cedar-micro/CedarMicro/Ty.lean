/-
  CedarMicro.Ty — the tiny type language our generator targets.

  Mirrors Palamedes/Data/STLC/Ty.lean's structure:
    1. `Ty`            base inductive (what the user writes)
    2. `TyF α`         companion functor (one arm per Ty constructor,
                        with recursive positions replaced by α)
    3. `TyF_or`        normal-form lemma rewriting TyF.rec into a
                        disjunctive-existential shape Aesop can case on
    4. `Ty.fold`       fold recursion scheme
    5. `Ty.accuM`      accumulating monadic fold — drives the
                        unfold strategy the paper describes
    6. `Ty.as_or`      rewrites `P t` into an ∨ over Ty constructors
    7. `Ty.deforest_eq` equality rewriting that collapses fused folds
                        into a structural compare

  Palamedes's `generator_search` Aesop tactic relies on
  `as_or` + `deforest_eq` being in scope (via `attribute [local simp]`
  in the invocation site), plus the functor + recursion-scheme
  primitives for closing anamorphism-shape goals.
-/

import Palamedes.Gen
import Palamedes.CorrectGen
import Palamedes.Total
import Palamedes.Util

section TypeDef

/-- Cedar-micro types. For V1 we cover just Bool and Int — the Cedar
    subset that exercises the generator-synthesis path without
    dragging in Set/Record/Entity ambiguity. -/
inductive Ty : Type where
  | bool
  | int
  deriving DecidableEq, Repr

end TypeDef

section BaseFunctor

/-- Companion functor. `Ty` has no recursive constructors (bool / int
    are both nullary), so `TyF α` is trivially a copy of `Ty`. We still
    define it explicitly to keep the parallel with the Palamedes STLC
    template — later Expr.lean's companion functor is non-trivial. -/
inductive TyF (α : Type) where
  | bool : TyF α
  | int : TyF α

/-- `TyF_or` — rewrite `TyF.rec P Q τ` into disjunctive-existential
    normal form Aesop can case on. No existentials since both arms
    are nullary. -/
theorem TyF_or
    {α : Type}
    {Pbool Pint : Prop}
    {τ : TyF α} :
    (match τ with | .bool => Pbool | .int => Pint) ↔
    (Pbool ∧ τ = .bool) ∨ (Pint ∧ τ = .int) := by
  match τ with
  | .bool => simp
  | .int => simp

end BaseFunctor

section RecursionSchemes

/-- Fold scheme — no recursion since Ty is flat, so this is just a
    dispatch table. Kept for symmetry with Palamedes's convention. -/
def Ty.fold {α : Type} (z_bool z_int : α) (τ : Ty) : α :=
  match τ with
  | .bool => z_bool
  | .int  => z_int

@[simp] theorem Ty.fold_bool : Ty.fold zb zi .bool = zb := rfl
@[simp] theorem Ty.fold_int  : Ty.fold zb zi .int  = zi := rfl

/-- Monadic accumulating fold. Again trivial since Ty is flat. -/
def Ty.accuM [Monad m] {α σ : Type}
    (f_bool : σ → m α) (f_int : σ → m α)
    (τ : Ty) (i : σ) : m α :=
  match τ with
  | .bool => f_bool i
  | .int  => f_int i

end RecursionSchemes

section Palamedes

/-- `Ty.as_or` — expresses `P t` for `t : Ty` as a disjunction indexed
    by the two constructors. Palamedes's Aesop rules pattern-match on
    this shape to generate case-arms. -/
theorem Ty.as_or {P : Ty → Prop} {τ : Ty} :
    P τ ↔ (P .bool ∧ τ = .bool) ∨ (P .int ∧ τ = .int) := by
  cases τ <;> simp

/-- `Ty.deforest_eq` — collapses `Ty.fold _ _ τ = x` through the
    structural cases on τ. Helps Aesop unify generator outputs
    against concrete types. -/
theorem Ty.deforest_eq {α : Type} {zb zi x : α} {τ : Ty} :
    Ty.fold zb zi τ = x ↔
    (zb = x ∧ τ = .bool) ∨ (zi = x ∧ τ = .int) := by
  cases τ <;> simp
