/-
  CedarMicro.Expr. the tiny expression grammar Palamedes generates.

  Mirrors Palamedes/Data/STLC/Term.lean structure. Five constructors:

    litInt  : Int → Expr                 nullary-data
    litBool : Bool → Expr                nullary-data
    var     : Nat → Expr                 nullary-data (de Bruijn index)
    ite     : Expr → Expr → Expr → Expr  ternary recursive
    and     : Expr → Expr → Expr         binary recursive

  Three of these are flat, two are recursive. enough to exercise
  Palamedes's catamorphism → anamorphism rewrite (the PLDI '26 core
  technique) without drowning the scaffolding port in recursive cases.
  If V1 closes on this, V2 scales to the full cedar-spec `Cedar.Spec.Expr`
  (12 constructors; records + sets + extensions still deferred).

  The contents parallel Ty.lean: inductive + companion functor +
  recursion-scheme theorems + `as_or` + `deforest_eq`. Palamedes's
  `generator_search` tactic reads all of these via `attribute
  [local simp]`.
-/

import Palamedes.Gen
import Palamedes.CorrectGen
import Palamedes.Total
import Palamedes.Util

namespace CedarMicro


inductive Expr : Type where
  | litInt  : Int → Expr
  | litBool : Bool → Expr
  | var     : Nat → Expr
  | ite     : Expr → Expr → Expr → Expr
  | and     : Expr → Expr → Expr
  deriving Repr



/-- Companion functor: recursive positions become `α`. The `ite` and
    `and` arms each pack one or more `α`s in place of the original
    `Expr` sub-expressions. -/
inductive ExprF (α : Type) where
  | litInt  : Int → ExprF α
  | litBool : Bool → ExprF α
  | var     : Nat → ExprF α
  | ite     : (c t f : α) → ExprF α
  | and     : (a b : α) → ExprF α

/-- `ExprF_or`. normalise an ExprF case-match into a disjunction of
    the five constructor shapes. This is the Aesop-friendly form
    Palamedes rules pattern-match on for the case-split step. -/
theorem ExprF_or
    {α : Type}
    {PlitI : Int → Prop}
    {PlitB : Bool → Prop}
    {Pvar : Nat → Prop}
    {Pite : α → α → α → Prop}
    {Pand : α → α → Prop}
    {e : ExprF α} :
    (match e with
      | .litInt n  => PlitI n
      | .litBool b => PlitB b
      | .var n     => Pvar n
      | .ite c t f => Pite c t f
      | .and a b   => Pand a b) ↔
    (∃ n, PlitI n ∧ e = .litInt n) ∨
    (∃ b, PlitB b ∧ e = .litBool b) ∨
    (∃ n, Pvar n ∧ e = .var n) ∨
    (∃ c t f, Pite c t f ∧ e = .ite c t f) ∨
    (∃ a b, Pand a b ∧ e = .and a b) := by
  match e with
  | .litInt _  => aesop
  | .litBool _ => aesop
  | .var _     => aesop
  | .ite _ _ _ => aesop
  | .and _ _   => aesop



/-- Fold. collapse an `Expr` into `α` by recursing on structure. One
    arm per constructor; recursive arms fold children first then
    combine. -/
def Expr.fold {α : Type}
    (flitI : Int → α)
    (flitB : Bool → α)
    (fvar : Nat → α)
    (fite : α → α → α → α)
    (fand : α → α → α)
    (e : Expr) : α :=
  match e with
  | .litInt n  => flitI n
  | .litBool b => flitB b
  | .var n     => fvar n
  | .ite c t f =>
      fite (Expr.fold flitI flitB fvar fite fand c)
           (Expr.fold flitI flitB fvar fite fand t)
           (Expr.fold flitI flitB fvar fite fand f)
  | .and a b =>
      fand (Expr.fold flitI flitB fvar fite fand a)
           (Expr.fold flitI flitB fvar fite fand b)

@[simp] theorem Expr.fold_litInt :
    Expr.fold flitI flitB fvar fite fand (.litInt n) = flitI n := rfl
@[simp] theorem Expr.fold_litBool :
    Expr.fold flitI flitB fvar fite fand (.litBool b) = flitB b := rfl
@[simp] theorem Expr.fold_var :
    Expr.fold flitI flitB fvar fite fand (.var n) = fvar n := rfl
@[simp] theorem Expr.fold_ite {c t f : Expr} :
    Expr.fold flitI flitB fvar fite fand (.ite c t f) =
    fite (Expr.fold flitI flitB fvar fite fand c)
         (Expr.fold flitI flitB fvar fite fand t)
         (Expr.fold flitI flitB fvar fite fand f) := rfl
@[simp] theorem Expr.fold_and {a b : Expr} :
    Expr.fold flitI flitB fvar fite fand (.and a b) =
    fand (Expr.fold flitI flitB fvar fite fand a)
         (Expr.fold flitI flitB fvar fite fand b) := rfl



/-- `Expr.as_or`. the big disjunctive-existential normal form that
    Palamedes's rules pattern-match for splitting into constructor
    cases during generator synthesis. -/
theorem Expr.as_or {P : Expr → Prop} {e : Expr} :
    P e ↔
    (∃ n, P (.litInt n) ∧ e = .litInt n) ∨
    (∃ b, P (.litBool b) ∧ e = .litBool b) ∨
    (∃ n, P (.var n) ∧ e = .var n) ∨
    (∃ c t f, P (.ite c t f) ∧ e = .ite c t f) ∨
    (∃ a b, P (.and a b) ∧ e = .and a b) := by
  cases e <;> aesop

/-- `Expr.deforest_eq`. collapse Expr.fold equality into a
    structural case analysis. This is the piece that lets the Aesop
    search compare generated-AST shapes against the target predicate
    without a combinatorial blowup. -/
theorem Expr.deforest_eq
    {α : Type} {flitI : Int → α} {flitB : Bool → α} {fvar : Nat → α}
    {fite : α → α → α → α} {fand : α → α → α} {x : α} {e : Expr} :
    Expr.fold flitI flitB fvar fite fand e = x ↔
    (∃ n, flitI n = x ∧ e = .litInt n) ∨
    (∃ b, flitB b = x ∧ e = .litBool b) ∨
    (∃ n, fvar n = x ∧ e = .var n) ∨
    (∃ c t f, fite (Expr.fold flitI flitB fvar fite fand c)
                   (Expr.fold flitI flitB fvar fite fand t)
                   (Expr.fold flitI flitB fvar fite fand f) = x ∧
               e = .ite c t f) ∨
    (∃ a b, fand (Expr.fold flitI flitB fvar fite fand a)
                 (Expr.fold flitI flitB fvar fite fand b) = x ∧
             e = .and a b) := by
  cases e <;> aesop

end CedarMicro
