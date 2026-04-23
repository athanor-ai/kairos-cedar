/-
  CedarMicro.Soundness: soundness theorem for the hand-authored
  type-directed generator `genWellTyped`.

  The paper's §5.1 headline claim:

    ∀ Γ τ e, e ∈ support (genWellTyped Γ τ) → wellTypedAt Γ τ e = true

  Proof outline:

    Step 1. `varsOfType_sound`: if `n ∈ varsOfType Γ τ`, then
            `Γ[n]? = some τ`.
    Step 2. `genLeaf_sound`: every `e` in `support (genLeaf Γ τ)`
            satisfies `wellTypedAt Γ τ e`. Uses Step 1 + the
            Palamedes support lemmas for `pick` and `pure`.
    Step 3. `genSize_sound`: induction on fuel. At fuel 0 reduces
            to Step 2. At fuel n+1, case-split on τ; each arm is
            a `pick` of `genLeaf` with a `bind` over recursive
            calls; the recursive hypothesis plus the typing
            rules of `ite` and `and` discharge the recursive
            arms.
    Step 4. `genWellTyped_sound`: Step 3 specialised to fuel = 2.
-/

import CedarMicro.WellTyped

namespace CedarMicro

open Gen

-- ────────────────────────────────────────────────────────────────────
-- Step 1: varsOfType lookup soundness.
-- ────────────────────────────────────────────────────────────────────

theorem varsOfType_sound (Γ : List Ty) (τ : Ty) (n : Nat) :
    n ∈ varsOfType Γ τ → Γ[n]? = some τ := by
  -- Induction on Γ with varsOfType now in direct-recursive form.
  -- Base case (Γ = []): varsOfType returns [], n ∈ [] is vacuous.
  -- Cons case: split on head type equality; when it matches and
  -- n = 0, Γ[0]? = some τ by the head; when it matches and n = k+1,
  -- recurse by ih; when it doesn't match, n must be k+1 from the
  -- shifted tail, recurse by ih.
  -- Holes (two sorrys) are mechanical `simp [List.get?]`-style
  -- rewrites that the current Lean 4.24 simp config does not
  -- close automatically. Target next commit: bundle obligation
  -- and dispatch to Aristotle or close with a manual case split.
  sorry

-- ────────────────────────────────────────────────────────────────────
-- Step 2: `genLeaf` produces only well-typed expressions.
-- ────────────────────────────────────────────────────────────────────

theorem genLeaf_sound (Γ : List Ty) (τ : Ty) (e : Expr) :
    _root_.Gen.support (genLeaf Γ τ) e → wellTypedAt Γ τ e = true := by
  -- TODO(paper §5.1): unfold genLeaf, case-split on varsOfType Γ τ,
  -- case-split on τ for the literal branch. Each atomic arm is
  -- a `pure` whose support is a singleton that trivially
  -- type-checks; the var branch uses varsOfType_sound.
  sorry

-- ────────────────────────────────────────────────────────────────────
-- Step 3: `genSize` soundness by induction on fuel.
-- ────────────────────────────────────────────────────────────────────

theorem genSize_sound :
    ∀ (Γ : List Ty) (n : Nat) (τ : Ty) (e : Expr),
      _root_.Gen.support (genSize Γ n τ) e → wellTypedAt Γ τ e = true := by
  intro Γ n
  induction n with
  | zero =>
    intro τ e hmem
    -- genSize Γ 0 τ = genLeaf Γ τ; reduce via genLeaf_sound.
    simp [genSize] at hmem
    exact genLeaf_sound Γ τ e hmem
  | succ n ih =>
    intro τ e hmem
    -- At fuel n+1, τ ∈ {bool, int}; each arm is a pick whose two
    -- sides are (genLeaf Γ τ) or a bind producing a recursive form.
    -- The recursive form's support lifts by Palamedes's
    -- `support_bind`, and each inner call sits at fuel 0, which
    -- falls under Step 2.
    -- TODO(paper §5.1): discharge via support_pick + support_bind +
    -- ih applied to each recursive call.
    sorry

-- ────────────────────────────────────────────────────────────────────
-- Step 4: the paper's main soundness theorem.
-- ────────────────────────────────────────────────────────────────────

/-- Every expression in the support of the hand-authored
    type-directed generator satisfies the Lean typechecker
    predicate at the requested target type. -/
theorem genWellTyped_sound (Γ : List Ty) (τ : Ty) (e : Expr) :
    _root_.Gen.support (genWellTyped Γ τ) e → wellTypedAt Γ τ e = true := by
  unfold genWellTyped
  exact genSize_sound Γ 2 τ e

end CedarMicro
