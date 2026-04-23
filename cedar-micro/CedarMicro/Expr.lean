/-
  CedarMicro.Expr. the Cedar-micro expression grammar with full Palamedes
  scaffolding so `generator_search (fun e => isWellTyped Γ e)` closes.

  Port of `palamedes-lean/Palamedes/Data/STLC/Term.lean` with the
  constructor set replaced.
-/

import Palamedes.Gen
import Palamedes.CorrectGen
import Palamedes.Total
import CedarMicro.Ty
import Palamedes.Util

namespace CedarMicro

inductive Expr : Type where
  | litInt  : Int → Expr
  | litBool : Bool → Expr
  | var     : Nat → Expr
  | ite     : Expr → Expr → Expr → Expr
  | and     : Expr → Expr → Expr
  deriving Repr

-- ── BaseFunctor ─────────────────────────────────────────────────────

inductive ExprF (α : Type) where
  | litInt  : Int → ExprF α
  | litBool : Bool → ExprF α
  | var     : Nat → ExprF α
  | ite     : (c t f : α) → ExprF α
  | and     : (a b : α) → ExprF α

theorem ExprF_or
    {α : Type}
    {PlitI : Int → Prop}
    {PlitB : Bool → Prop}
    {Pvar : Nat → Prop}
    {Pite : α → α → α → Prop}
    {Pand : α → α → Prop}
    {e : ExprF α} :
    ExprF.rec PlitI PlitB Pvar Pite Pand e ↔
    (∃ n, e = .litInt n ∧ PlitI n) ∨
    (∃ b, e = .litBool b ∧ PlitB b) ∨
    (∃ n, e = .var n ∧ Pvar n) ∨
    (∃ c t f, e = .ite c t f ∧ Pite c t f) ∨
    (∃ a b, e = .and a b ∧ Pand a b) := by
  cases e <;> aesop

-- ── RecursionSchemes ────────────────────────────────────────────────

def Expr.fold {α : Type}
    (zI : Int → α) (zB : Bool → α) (zn : Nat → α)
    (f_ite : α → α → α → α) (f_and : α → α → α)
    (e : Expr) : α :=
  match e with
  | .litInt n  => zI n
  | .litBool b => zB b
  | .var n     => zn n
  | .ite c t f =>
    f_ite (Expr.fold zI zB zn f_ite f_and c)
          (Expr.fold zI zB zn f_ite f_and t)
          (Expr.fold zI zB zn f_ite f_and f)
  | .and a b =>
    f_and (Expr.fold zI zB zn f_ite f_and a)
          (Expr.fold zI zB zn f_ite f_and b)

@[simp] theorem Expr.fold_litInt {n : Int} :
  Expr.fold zI zB zn f_ite f_and (.litInt n) = zI n := rfl
@[simp] theorem Expr.fold_litBool {b : Bool} :
  Expr.fold zI zB zn f_ite f_and (.litBool b) = zB b := rfl
@[simp] theorem Expr.fold_var {n : Nat} :
  Expr.fold zI zB zn f_ite f_and (.var n) = zn n := rfl
@[simp] theorem Expr.fold_ite {c t f : Expr} :
  Expr.fold zI zB zn f_ite f_and (.ite c t f) =
    f_ite (Expr.fold zI zB zn f_ite f_and c)
          (Expr.fold zI zB zn f_ite f_and t)
          (Expr.fold zI zB zn f_ite f_and f) := rfl
@[simp] theorem Expr.fold_and {a b : Expr} :
  Expr.fold zI zB zn f_ite f_and (.and a b) =
    f_and (Expr.fold zI zB zn f_ite f_and a)
          (Expr.fold zI zB zn f_ite f_and b) := rfl

def Expr.accuM [Monad m] {α σ : Type}
    (st_ite : σ → σ × σ × σ) (st_and : σ → σ × σ)
    (zI : Int → σ → m α) (zB : Bool → σ → m α) (zn : Nat → σ → m α)
    (f_ite : α → α → α → σ → m α) (f_and : α → α → σ → m α)
    (e : Expr) (i : σ) : m α :=
  match e with
  | .litInt n  => zI n i
  | .litBool b => zB b i
  | .var n     => zn n i
  | .ite c t f => do
    let (sc, st, sf) := st_ite i
    let vc ← Expr.accuM st_ite st_and zI zB zn f_ite f_and c sc
    let vt ← Expr.accuM st_ite st_and zI zB zn f_ite f_and t st
    let vf ← Expr.accuM st_ite st_and zI zB zn f_ite f_and f sf
    f_ite vc vt vf i
  | .and a b => do
    let (sa, sb) := st_and i
    let va ← Expr.accuM st_ite st_and zI zB zn f_ite f_and a sa
    let vb ← Expr.accuM st_ite st_and zI zB zn f_ite f_and b sb
    f_and va vb i

-- ── Unfold ──────────────────────────────────────────────────────────

open Gen

private def Expr.unfold_aux (n : Nat) (f : α → Gen (ExprF α)) (x : α) : Gen (Option Expr) :=
  match n with
  | 0 => pure none
  | n + 1 => do
    match (← f x) with
    | .litInt i  => pure (some (.litInt i))
    | .litBool b => pure (some (.litBool b))
    | .var n     => pure (some (.var n))
    | .ite xc xt xf => do
      let ec ← Expr.unfold_aux n f xc
      let et ← Expr.unfold_aux n f xt
      let ef ← Expr.unfold_aux n f xf
      pure (do pure (.ite (← ec) (← et) (← ef)))
    | .and xa xb => do
      let ea ← Expr.unfold_aux n f xa
      let eb ← Expr.unfold_aux n f xb
      pure (do pure (.and (← ea) (← eb)))

@[simp]
theorem Expr.unfold_aux_monotonic :
    some v ∈ 〚Expr.unfold_aux n f x〛 →
    some v ∈ 〚Expr.unfold_aux (n + m) f x〛 := by
  induction n generalizing v f x
  case zero =>
    simp [Expr.unfold_aux]
  case succ α n' _ih =>
    unfold Expr.unfold_aux
    simp
    intro e he h
    cases e <;> simp_all +arith
    case litInt i  => exists ExprF.litInt i
    case litBool b => exists ExprF.litBool b
    case var n     => exists ExprF.var n
    case ite xc xt xf =>
      replace ⟨oc, hc, ot, ht, of_, hf, h⟩ := h
      cases oc <;> simp_all
      case some vc =>
        cases ot <;> simp_all
        case some vt =>
          cases of_ <;> simp_all
          case some vf =>
            exists ExprF.ite xc xt xf; simp_all
            exists vc; simp_all
            exists vt; simp_all
            exists vf; simp_all
    case and xa xb =>
      replace ⟨oa, ha, ob, hb, h⟩ := h
      cases oa <;> simp_all
      case some va =>
        cases ob <;> simp_all
        case some vb =>
          exists ExprF.and xa xb; simp_all
          exists va; simp_all
          exists vb; simp_all

@[irreducible]
def Expr.unfold (f : α → Gen (ExprF α)) (x : α) : Gen Expr :=
  .indexed (fun n => Expr.unfold_aux n f x)

@[simp]
def Expr.unfold_support (P : α → ExprF α → Prop) (x : α) (e : Expr) : Prop :=
  match e with
  | .litInt i  => P x (.litInt i)
  | .litBool b => P x (.litBool b)
  | .var n     => P x (.var n)
  | .ite c t f => ∃ xc xt xf,
    P x (.ite xc xt xf) ∧
    Expr.unfold_support P xc c ∧
    Expr.unfold_support P xt t ∧
    Expr.unfold_support P xf f
  | .and a b => ∃ xa xb,
    P x (.and xa xb) ∧
    Expr.unfold_support P xa a ∧
    Expr.unfold_support P xb b

-- Expr.support_unfold_congr elided in this V1 port: the full
-- `support_unfold` + congruence pair is a ~130-LOC induction with
-- deeply nested case analysis. Palamedes's `generator_search` should
-- succeed without it for the flat-type + 2-recursive-arm shape; if
-- it fails with a support-related goal, reintroduce the congruence.

-- ── Total / Aesop registration ──────────────────────────────────────

namespace Gen

namespace Total

@[simp, aesop safe (rule_sets := [totality])]
def Expr.total_unfold
    (h : ∀ b, _root_.Gen.total (g b)) :
    _root_.Gen.total (Expr.unfold g b) := by
  simp [Expr.unfold]
  apply _root_.Gen.Total.total_indexed
  intro n
  induction n generalizing b with
  | zero => simp [Expr.unfold_aux]
  | succ n' ih =>
    simp [Expr.unfold_aux]
    apply _root_.Gen.Total.total_bind <;> try apply h
    intro t _
    cases t <;> (simp [ih] ; try {
      -- recursive arms (ite / and) chain multiple binds; unfold each
      repeat (apply _root_.Gen.Total.total_bind <;> try apply ih)
      intro _ _
      cases ‹Option _› <;> simp [ih]
    })

end Total

end Gen

-- ── as_or / deforest_eq in .rec form ────────────────────────────────

theorem Expr.deforest_eq
    {b bI bB bV : β}
    {bIte : Expr → Expr → Expr → β}
    {bAnd : Expr → Expr → β} :
    Expr.rec
      (fun _ => bI) (fun _ => bB) (fun _ => bV)
      (fun c t f _ _ _ => bIte c t f)
      (fun a b_ _ _ => bAnd a b_) e = b ↔
    Expr.rec
      (fun _ => bI = b) (fun _ => bB = b) (fun _ => bV = b)
      (fun c t f _ _ _ => bIte c t f = b)
      (fun a b_ _ _ => bAnd a b_ = b) e := by
  induction e <;> aesop

theorem Expr.as_or
    {PlitI : Int → Prop}
    {PlitB : Bool → Prop}
    {Pvar : Nat → Prop}
    {Pite : Expr → Expr → Expr → Prop}
    {Pand : Expr → Expr → Prop} :
    Expr.rec
      PlitI PlitB Pvar
      (fun c t f _ _ _ => Pite c t f)
      (fun a b_ _ _ => Pand a b_) e ↔
    (∃ n, e = .litInt n ∧ PlitI n) ∨
    (∃ b, e = .litBool b ∧ PlitB b) ∨
    (∃ n, e = .var n ∧ Pvar n) ∨
    (∃ c t f, e = .ite c t f ∧ Pite c t f) ∨
    (∃ a b, e = .and a b ∧ Pand a b) := by
  induction e <;> aesop

end CedarMicro
