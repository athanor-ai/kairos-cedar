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

    Proof strategy: two private helpers (`getType_ite_eq_some_iff`,
    `getType_and_eq_some_iff`) characterise the do-chain in
    `getType` for each compound constructor. Key technical point:
    after `simp [getType, ...]` reduces the bind chain, the guard
    conditions surface as `match guard (τ = T), ...` which requires
    `simp only [_root_.guard, pure]` + `split_ifs` to split on
    the if-then-else. The Lean 4.24 workbench container does NOT
    reduce the `guard` automatically from `simp [getType]` alone. -/
-- Helper: unfold the `ite` do-chain.
private theorem getType_ite_eq_some_iff (c t f : Expr) (Γ : List Ty) (τ : Ty) :
    getType (.ite c t f) Γ = some τ ↔
    getType c Γ = some .bool ∧ getType t Γ = some τ ∧ getType f Γ = some τ := by
  constructor
  · intro h
    rcases hc : getType c Γ with _ | τc
    · simp [getType, hc] at h
    rcases ht : getType t Γ with _ | τt
    · simp [getType, hc, ht] at h
    rcases hf : getType f Γ with _ | τf
    · simp [getType, hc, ht, hf] at h
    simp [getType, hc, ht, hf] at h
    -- h contains: match guard (τc = Ty.bool), fun _ => ... with | none, _ => none | some a, f => f a
    -- Unfold guard to if-then-else, then split_ifs
    simp only [_root_.guard, pure] at h
    split_ifs at h with hcb htf <;> simp_all [Option.some.injEq] <;>
      (first | (subst_eqs; exact ⟨hc.trans (hcb ▸ rfl), ht, htf ▸ hf⟩) | simp at h)
  · rintro ⟨hc, ht, hf⟩
    simp [getType, hc, ht, hf, _root_.guard, pure]

-- Helper: unfold the `and` do-chain.
private theorem getType_and_eq_some_iff (a b : Expr) (Γ : List Ty) (τ : Ty) :
    getType (.and a b) Γ = some τ ↔
    τ = .bool ∧ getType a Γ = some .bool ∧ getType b Γ = some .bool := by
  constructor
  · intro h
    rcases ha : getType a Γ with _ | τa
    · simp [getType, ha] at h
    rcases hb : getType b Γ with _ | τb
    · simp [getType, ha, hb] at h
    simp [getType, ha, hb] at h
    simp only [_root_.guard, pure] at h
    split_ifs at h with hab hbb <;> simp_all [Option.some.injEq] <;>
      (first | (subst_eqs; exact ⟨rfl, ha.trans (hab ▸ rfl), hb.trans (hbb ▸ rfl)⟩) | simp at h)
  · rintro ⟨rfl, ha, hb⟩
    simp [getType, ha, hb, _root_.guard, pure]

private theorem getType_eq_some_iff_hasType (e : Expr) (Γ : List Ty) (τ : Ty) :
    getType e Γ = some τ ↔ HasType Γ τ e := by
  constructor
  · -- Forward: getType e Γ = some τ → HasType Γ τ e
    induction e generalizing Γ τ with
    | litInt n =>
      simp [getType]; intro h; subst h; exact HasType.litInt Γ n
    | litBool b =>
      simp [getType]; intro h; subst h; exact HasType.litBool Γ b
    | var n =>
      simp [getType]; intro h; exact HasType.var Γ n τ h
    | ite c t f ihc iht ihf =>
      rw [getType_ite_eq_some_iff]
      rintro ⟨hc, ht, hf⟩
      exact HasType.ite Γ τ c t f (ihc Γ .bool hc) (iht Γ τ ht) (ihf Γ τ hf)
    | and a b iha ihb =>
      rw [getType_and_eq_some_iff]
      rintro ⟨rfl, ha, hb⟩
      exact HasType.and Γ a b (iha Γ .bool ha) (ihb Γ .bool hb)
  · -- Backward: HasType Γ τ e → getType e Γ = some τ
    intro h
    induction h with
    | litInt => simp [getType]
    | litBool => simp [getType]
    | var => simp_all [getType]
    | ite =>
      simp only [getType_ite_eq_some_iff]
      -- IHs are: getType c Γ = some .bool, getType t Γ = some τ, getType f Γ = some τ
      -- which come from the recursive HasType sub-derivations
      rename_i ihc iht ihf
      exact ⟨ihc, iht, ihf⟩
    | and =>
      simp only [getType_and_eq_some_iff]
      rename_i iha ihb
      exact ⟨trivial, iha, ihb⟩

theorem isWellTyped_iff_hasType (Γ : List Ty) (e : Expr) :
    isWellTyped Γ e ↔ ∃ τ, HasType Γ τ e := by
  simp only [isWellTyped]
  constructor
  · rintro ⟨τ, hτ⟩
    exact ⟨τ, (getType_eq_some_iff_hasType e Γ τ).mp hτ⟩
  · rintro ⟨τ, hτ⟩
    exact ⟨τ, (getType_eq_some_iff_hasType e Γ τ).mpr hτ⟩

end CedarMicro
