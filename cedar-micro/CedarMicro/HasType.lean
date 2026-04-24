/-
  CedarMicro.HasType: inductive typing judgment for Palamedes's
  generator_search.

  Palamedes's `generator_search` Aesop rule-set inverts inductive
  relations. The functional predicate `isWellTyped` (∃ over
  `getType`) does not expose intro rules for Aesop to case-split,
  so `generator_search` cannot fire against it (observation
  2026-04-24; see a follow-up issue).

  `HasType Γ τ e` is the inductive shadow of `getType`. It has one
  intro rule per Expr constructor. The biconditional with
  `isWellTyped` is sorry-stubbed in this first pass; closure is
  follow-up work that needs proper case analysis on the
  Option-bind + guard structure of `getType`.
-/

import CedarMicro.WellTyped

namespace CedarMicro

/-- Inductive typing judgment for CedarMicro. `HasType Γ τ e`
    says `e` has type `τ` under environment `Γ`. One intro rule
    per Expr constructor; all rules directly mirror the dispatch
    in `getType`. -/
inductive HasType : List Ty → Ty → Expr → Prop where
  | litInt  (Γ : List Ty) (n : Int) :
      HasType Γ .int (.litInt n)
  | litBool (Γ : List Ty) (b : Bool) :
      HasType Γ .bool (.litBool b)
  | var (Γ : List Ty) (n : Nat) (τ : Ty) :
      Γ[n]? = some τ → HasType Γ τ (.var n)
  | ite (Γ : List Ty) (τ : Ty) (c t f : Expr) :
      HasType Γ .bool c → HasType Γ τ t → HasType Γ τ f →
      HasType Γ τ (.ite c t f)
  | and (Γ : List Ty) (a b : Expr) :
      HasType Γ .bool a → HasType Γ .bool b →
      HasType Γ .bool (.and a b)

/-- Equivalence: isWellTyped is ∃ over getType; HasType is the
    inductive shadow. They quantify over the same set.

    follow-up: closure needs case analysis on the
    Option-bind + guard structure of `getType`, which Lean 4.24's
    simp config inside the workbench container does not fold
    automatically (verified 2026-04-24 in the .and arm, after
    `simp only [getType, iha, ihb]` the goal still shows the
    explicit `do … τa ← … τb ← …` chain). Left as `sorry` so the
    inductive itself can be imported + targeted by
    `generator_search` even before the biconditional closes. -/
theorem isWellTyped_iff_hasType (Γ : List Ty) (e : Expr) :
    isWellTyped Γ e ↔ ∃ τ, HasType Γ τ e := by
  sorry

end CedarMicro
