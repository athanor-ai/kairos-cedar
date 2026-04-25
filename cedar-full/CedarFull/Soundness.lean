/-
  CedarFull.Soundness: soundness theorem for the hand-authored
  type-directed generator `genWellTyped`.

  Headline claim (paper §5.1 analogue for the full Cedar type system):

    ∀ env τ e, e ∈ support (genWellTyped env τ) → isWellTyped env e

  Proof outline (mirrors CedarMicro.Soundness four steps):

    Step 1. `varsOfType_sound`: if `v ∈ varsOfType env τ`, then
            `typeOf (.var v) [] env` returns `.ok _`.
    Step 2. `litGen_sound`: every `e` in `support (litGen τ)` satisfies
            `isWellTyped env e` for primitive types.
    Step 3. `genLeaf_sound`: every `e` in `support (genLeaf env τ)`
            satisfies `isWellTyped env e`. Uses Steps 1–2.
    Step 4. `genSize_sound`: induction on fuel. At fuel 0 reduces to
            Step 3. At fuel n+1, leaf arms close via Step 3. Compound
            arms (and/or/ite/unaryApp/binaryApp) are sorry-stubbed
            pending typeOf inversion lemmas (future work).
    Step 5. `genWellTyped_sound`: Step 4 specialised to fuel = 3.

  V1 sorry inventory (7 total, all in compound arms of genSize_sound):
    • .bool: and-arm, or-arm, ite-arm           (3 sorrys)
    • .int:  add-arm, neg-arm, ite-arm           (3 sorrys)
    • .entity: ite-arm                           (1 sorry)
  All flat/leaf arms are closed without sorry.

  Closing the compound arms requires more than a drop-in inversion
  lemma. The current `genSize_sound` statement threads
  `wellTypedAt env e = true` (exists some type), but cedar-spec's
  `typeOfAnd` / `typeOfOr` / `typeOfIf` / `typeOfBinaryApp` dispatch
  on the *specific* type of each sub-expression. The inversion
  needs a target-type-indexed predicate like
  `wellTypedAtTy env τ e` (true iff `typeOf e [] env = .ok (te, _)`
  with `te.typeOf = τ`). Genuinely a refactor + per-arm lemma,
  not a seven-line fix. This refactor is future work.
-/

import CedarFull.Expr

namespace CedarFull

open Cedar.Spec
open Cedar.Validation
open CedarBridge
open Gen.Support

-- ────────────────────────────────────────────────────────────────────
-- Auxiliary: isWellTyped ↔ wellTypedAt = true
-- ────────────────────────────────────────────────────────────────────

theorem isWellTyped_iff (env : TypeEnv) (e : Expr) :
    isWellTyped env e ↔ wellTypedAt env e = true := by
  simp only [isWellTyped, wellTypedAt]
  constructor
  · rintro ⟨te, c, h⟩; simp [h]
  · intro h
    split at h
    · rename_i pair heq
      exact ⟨pair.1, pair.2, by rw [← heq]⟩
    · simp at h

theorem wellTypedAt_imp_isWellTyped (env : TypeEnv) (e : Expr)
    (h : wellTypedAt env e = true) : isWellTyped env e :=
  (isWellTyped_iff env e).mpr h

-- ────────────────────────────────────────────────────────────────────
-- Step 1: varsOfType lookup soundness.
-- ────────────────────────────────────────────────────────────────────

theorem varsOfType_sound (env : TypeEnv) (τ : CedarType) (v : Var) :
    v ∈ varsOfType env τ →
    ∃ te c, Cedar.Validation.typeOf (.var v) [] env = .ok (te, c) := by
  simp only [varsOfType, List.mem_append]
  intro _
  simp [Cedar.Validation.typeOf, Cedar.Validation.typeOfVar, Cedar.Validation.ok]
  cases v <;> exact ⟨_, _, rfl⟩

-- ────────────────────────────────────────────────────────────────────
-- Step 2: litGen produces only well-typed expressions.
-- ────────────────────────────────────────────────────────────────────

private theorem lit_bool_wellTyped (env : TypeEnv) (b : Bool) :
    wellTypedAt env (.lit (.bool b)) = true := by
  cases b <;>
    simp [wellTypedAt, Cedar.Validation.typeOf, Cedar.Validation.typeOfLit,
          Cedar.Validation.ok]

private theorem lit_int_wellTyped (env : TypeEnv) :
    wellTypedAt env (.lit (.int 0)) = true := by
  simp [wellTypedAt, Cedar.Validation.typeOf, Cedar.Validation.typeOfLit,
        Cedar.Validation.ok]

private theorem lit_string_wellTyped (env : TypeEnv) :
    wellTypedAt env (.lit (.string "")) = true := by
  simp [wellTypedAt, Cedar.Validation.typeOf, Cedar.Validation.typeOfLit,
        Cedar.Validation.ok]

theorem litGen_sound (env : TypeEnv) (τ : CedarType) (e : Expr)
    (h : Gen.support (litGen τ) e) : wellTypedAt env e = true := by
  -- Unfold Gen.support and litGen; then case-split on τ.
  simp only [Gen.support, litGen] at h
  split at h
  · -- .bool bty: litGen produces [true, false] via Gen.pick
    simp only [Gen.pick, Gen.ret, Pure.pure, List.mem_append,
               List.mem_cons, List.mem_nil_iff, or_false] at h
    rcases h with rfl | rfl <;> exact lit_bool_wellTyped env _
  · -- .int: litGen produces [int 0] via pure
    simp only [Gen.ret, Pure.pure, List.mem_singleton] at h
    subst h; exact lit_int_wellTyped env
  · -- .string: litGen produces [string ""] via pure
    simp only [Gen.ret, Pure.pure, List.mem_singleton] at h
    subst h; exact lit_string_wellTyped env
  · -- fallthrough (entity/set/record/ext): produces [bool false]
    simp only [Gen.ret, Pure.pure, List.mem_singleton] at h
    subst h; exact lit_bool_wellTyped env false

-- ────────────────────────────────────────────────────────────────────
-- Step 2b: varGen produces only well-typed expressions.
-- ────────────────────────────────────────────────────────────────────

private theorem varGen_sound (env : TypeEnv) (vars : List Var) (e : Expr)
    (h : Gen.support (varGen vars) e) : wellTypedAt env e = true := by
  simp only [Gen.support, varGen, List.mem_map] at h
  obtain ⟨v, _, rfl⟩ := h
  -- Every Var typechecks under typeOfVar (which always returns .ok)
  cases v <;>
    simp [wellTypedAt, Cedar.Validation.typeOf, Cedar.Validation.typeOfVar,
          Cedar.Validation.ok]

-- ────────────────────────────────────────────────────────────────────
-- Step 3: genLeaf produces only well-typed expressions.
-- ────────────────────────────────────────────────────────────────────

theorem genLeaf_sound (env : TypeEnv) (τ : CedarType) (e : Expr)
    (h : Gen.support (genLeaf env τ) e) : wellTypedAt env e = true := by
  simp only [genLeaf, support_pick] at h
  rcases h with hvg | hlit
  · exact varGen_sound env (varsOfType env τ) e hvg
  · exact litGen_sound env τ e hlit

-- ────────────────────────────────────────────────────────────────────
-- Step 3b: capability-independent typing for genLeaf outputs.
--
-- genLeaf env (.bool .anyBool) produces only bool literals
-- (.lit (.bool true) or .lit (.bool false)), whose typeOf result
-- does not depend on the input capability set.  This lets us discharge
-- the `typeOf t (c ∪ c₁) env` goal that appears in typeOfIf's .tt branch
-- by folding c₁ = [] (the empty output capabilities of a bool literal).
-- ────────────────────────────────────────────────────────────────────

/-- varsOfType env (.bool .anyBool) is always empty: no Cedar Var has bool type. -/
private theorem varsOfType_boolAnyBool_empty (env : TypeEnv) :
    varsOfType env (.bool .anyBool) = [] := by
  simp only [varsOfType]
  -- .bool .anyBool ≠ .entity _, .entity _, .entity _, .record _ for any env
  have h1 : (.bool .anyBool : CedarType) ≠ .entity env.reqty.principal := by simp
  have h2 : (.bool .anyBool : CedarType) ≠ .entity env.reqty.action.ty := by simp
  have h3 : (.bool .anyBool : CedarType) ≠ .entity env.reqty.resource := by simp
  have h4 : (.bool .anyBool : CedarType) ≠ .record env.reqty.context := by simp
  simp [h1, h2, h3, h4]

/-- Bool-literal membership in support (genLeaf env (.bool .anyBool)).
    varsOfType never returns a bool-typed var (all four Cedar Var
    constructors have entity or record type), so the only outputs are
    the two bool lits. -/
private theorem genLeaf_boolAnyBool_is_lit (env : TypeEnv) (c : Expr)
    (h : Gen.support (genLeaf env (.bool .anyBool)) c) :
    c = .lit (.bool true) ∨ c = .lit (.bool false) := by
  simp only [genLeaf, Gen.support, Gen.pick, varGen, litGen,
             Gen.ret, Pure.pure, List.mem_append,
             List.mem_cons, List.mem_nil_iff, false_or, or_false,
             varsOfType_boolAnyBool_empty, List.map_nil] at h
  -- h is now: c = .lit (.bool true) ∨ c = .lit (.bool false)
  rcases h with rfl | rfl
  · exact Or.inl rfl
  · exact Or.inr rfl

/-- If `c` is a bool literal, `t` and `f` type-check under `env`, then
    `.ite c t f` type-checks under `env`.  Used to close the `.entity .ite`
    arm of `genSize_sound`. -/
private theorem wellTypedAt_ite_of_boolLit (env : TypeEnv) (c t f : Expr)
    (hclit : c = .lit (.bool true) ∨ c = .lit (.bool false))
    (ht : wellTypedAt env t = true)
    (hf : wellTypedAt env f = true) :
    wellTypedAt env (.ite c t f) = true := by
  -- Extract .ok witnesses from wellTypedAt hypotheses
  simp only [wellTypedAt] at ht hf ⊢
  -- wellTypedAt env t = true means typeOf t [] env = .ok _
  have ⟨resTok_t, heqt⟩ : ∃ res, typeOf t [] env = .ok res := by
    revert ht; cases h : typeOf t [] env <;> simp
  have ⟨resTok_f, heqf⟩ : ∃ res, typeOf f [] env = .ok res := by
    revert hf; cases h : typeOf f [] env <;> simp
  -- Case-split on c being true-lit or false-lit
  rcases hclit with rfl | rfl
  · -- c = .lit (.bool true):
    --   typeOf (.lit (.bool true)) [] env = .ok (TypedExpr.lit (.bool true) (.bool .tt), [])
    --   typeOfIf dispatches on .bool .tt → uses then-branch only, no lub needed
    -- Show [] ∪ ∅ = [] so typeOf t can be applied with heqt
    have hcap : ([] : Capabilities) ∪ ∅ = [] := by simp [List.union_def]
    simp only [Cedar.Validation.typeOf, Cedar.Validation.typeOfLit, Cedar.Validation.ok,
               Function.comp_apply, Except.bind_ok, Cedar.Validation.typeOfIf,
               TypedExpr.typeOf, hcap, heqt]
  · -- c = .lit (.bool false):
    --   typeOfIf dispatches on .bool .ff → uses else-branch only, no lub needed
    simp only [Cedar.Validation.typeOf, Cedar.Validation.typeOfLit, Cedar.Validation.ok,
               Function.comp_apply, Except.bind_ok, Cedar.Validation.typeOfIf,
               TypedExpr.typeOf, heqf]

-- ────────────────────────────────────────────────────────────────────
-- Step 3c: integer-literal characterisation of genLeaf env .int
-- ────────────────────────────────────────────────────────────────────

/-- varsOfType env .int is always empty: no Cedar Var has int type. -/
private theorem varsOfType_int_empty (env : TypeEnv) :
    varsOfType env .int = [] := by
  simp only [varsOfType]
  have h1 : (CedarType.int : CedarType) ≠ .entity env.reqty.principal := by simp
  have h2 : (CedarType.int : CedarType) ≠ .entity env.reqty.action.ty := by simp
  have h3 : (CedarType.int : CedarType) ≠ .entity env.reqty.resource := by simp
  have h4 : (CedarType.int : CedarType) ≠ .record env.reqty.context := by simp
  simp [h1, h2, h3, h4]

/-- genLeaf env .int only produces .lit (.int 0). -/
private theorem genLeaf_int_is_intLit (env : TypeEnv) (e : Expr)
    (h : Gen.support (genLeaf env .int) e) :
    e = .lit (.int 0) := by
  simp only [genLeaf, Gen.support, Gen.pick, varGen, litGen,
             Gen.ret, Pure.pure, List.mem_append,
             List.mem_singleton, List.mem_nil_iff, false_or,
             varsOfType_int_empty, List.map_nil] at h
  exact h

/-- typeOf (.lit (.int 0)) [] env returns a typed expr with typeOf = .int. -/
private theorem typeOf_intLit_is_int (env : TypeEnv) :
    ∃ te, typeOf (.lit (.int 0)) [] env = .ok (te, []) ∧ te.typeOf = .int := by
  simp only [Cedar.Validation.typeOf, Cedar.Validation.typeOfLit, Cedar.Validation.ok,
             Function.comp_apply]
  exact ⟨TypedExpr.lit (.int 0) .int, rfl, rfl⟩

/-- Given `a` is an int literal (in support of genLeaf env .int) and
    `b` is an int literal, `.binaryApp .add a b` type-checks as .int. -/
private theorem wellTypedAt_binaryApp_add_of_intLits (env : TypeEnv) (a b : Expr)
    (ha : Gen.support (genLeaf env .int) a)
    (hb : Gen.support (genLeaf env .int) b) :
    wellTypedAt env (.binaryApp .add a b) = true := by
  have heqa := genLeaf_int_is_intLit env a ha
  have heqb := genLeaf_int_is_intLit env b hb
  subst heqa; subst heqb
  -- typeOf (.lit (.int 0)) [] env = .ok (TypedExpr.lit (.int 0) .int, [])
  -- so typeOfBinaryApp .add with both .int types gives .ok .int
  simp only [wellTypedAt, Cedar.Validation.typeOf, Cedar.Validation.typeOfLit,
             Cedar.Validation.ok, Function.comp_apply, Except.bind_ok,
             Cedar.Validation.typeOfBinaryApp, TypedExpr.typeOf]

/-- Given `a` is an int literal (in support of genLeaf env .int),
    `.unaryApp .neg a` type-checks as .int. -/
private theorem wellTypedAt_unaryApp_neg_of_intLit (env : TypeEnv) (a : Expr)
    (ha : Gen.support (genLeaf env .int) a) :
    wellTypedAt env (.unaryApp .neg a) = true := by
  have heqa := genLeaf_int_is_intLit env a ha
  subst heqa
  simp only [wellTypedAt, Cedar.Validation.typeOf, Cedar.Validation.typeOfLit,
             Cedar.Validation.ok, Function.comp_apply, Except.bind_ok,
             Cedar.Validation.typeOfUnaryApp, TypedExpr.typeOf]

-- ────────────────────────────────────────────────────────────────────
-- Step 3d: bool-literal helpers for .and and .or
-- ────────────────────────────────────────────────────────────────────

/-- Given `a` and `b` are bool literals, `.and a b` type-checks. -/
private theorem wellTypedAt_and_of_boolLits (env : TypeEnv) (a b : Expr)
    (ha : a = .lit (.bool true) ∨ a = .lit (.bool false))
    (hb : b = .lit (.bool true) ∨ b = .lit (.bool false)) :
    wellTypedAt env (.and a b) = true := by
  rcases ha with rfl | rfl <;> rcases hb with rfl | rfl <;>
    simp [wellTypedAt, Cedar.Validation.typeOf, Cedar.Validation.typeOfLit,
          Cedar.Validation.ok, Cedar.Validation.typeOfAnd, List.union_def,
          TypedExpr.typeOf]

/-- Given `a` and `b` are bool literals, `.or a b` type-checks. -/
private theorem wellTypedAt_or_of_boolLits (env : TypeEnv) (a b : Expr)
    (ha : a = .lit (.bool true) ∨ a = .lit (.bool false))
    (hb : b = .lit (.bool true) ∨ b = .lit (.bool false)) :
    wellTypedAt env (.or a b) = true := by
  rcases ha with rfl | rfl <;> rcases hb with rfl | rfl <;>
    simp [wellTypedAt, Cedar.Validation.typeOf, Cedar.Validation.typeOfLit,
          Cedar.Validation.ok, Cedar.Validation.typeOfOr, TypedExpr.typeOf]

-- ────────────────────────────────────────────────────────────────────
-- Step 4: genSize soundness by induction on fuel.
-- ────────────────────────────────────────────────────────────────────

theorem genSize_sound :
    ∀ (env : TypeEnv) (n : Nat) (τ : CedarType) (e : Expr),
      Gen.support (genSize env n τ) e → isWellTyped env e := by
  intro env n
  induction n with
  | zero =>
    intro τ e hmem
    simp only [genSize] at hmem
    exact wellTypedAt_imp_isWellTyped env e (genLeaf_sound env τ e hmem)
  | succ n _ih =>
    intro τ e hmem
    cases τ with
    -- ── .bool ──────────────────────────────────────────────────────
    | bool bty =>
      simp only [genSize] at hmem
      simp only [support_pick, support_bind, support_pure] at hmem
      rcases hmem with hleaf | hand | hor | hite
      · exact wellTypedAt_imp_isWellTyped env e
          (genLeaf_sound env (.bool bty) e hleaf)
      · obtain ⟨a, ha, b, hb, rfl⟩ := hand
        -- a, b come from genLeaf env (.bool .anyBool) = bool literals only.
        have halit := genLeaf_boolAnyBool_is_lit env a ha
        have hblit := genLeaf_boolAnyBool_is_lit env b hb
        exact wellTypedAt_imp_isWellTyped env (.and a b)
          (wellTypedAt_and_of_boolLits env a b halit hblit)
      · obtain ⟨a, ha, b, hb, rfl⟩ := hor
        -- a, b come from genLeaf env (.bool .anyBool) = bool literals only.
        have halit := genLeaf_boolAnyBool_is_lit env a ha
        have hblit := genLeaf_boolAnyBool_is_lit env b hb
        exact wellTypedAt_imp_isWellTyped env (.or a b)
          (wellTypedAt_or_of_boolLits env a b halit hblit)
      · obtain ⟨c, hc, t, ht, f, hf, rfl⟩ := hite
        -- c comes from genSize env 0 (.bool .anyBool) = genLeaf env (.bool .anyBool)
        -- which only produces .lit (.bool true) or .lit (.bool false).
        have hc2 : Gen.support (genLeaf env (.bool .anyBool)) c := hc
        have ht2 : Gen.support (genLeaf env (.bool bty)) t := ht
        have hf2 : Gen.support (genLeaf env (.bool bty)) f := hf
        have hclit := genLeaf_boolAnyBool_is_lit env c hc2
        have ht'   := genLeaf_sound env (.bool bty) t ht2
        have hf'   := genLeaf_sound env (.bool bty) f hf2
        exact wellTypedAt_imp_isWellTyped env (.ite c t f)
          (wellTypedAt_ite_of_boolLit env c t f hclit ht' hf')
    -- ── .int ───────────────────────────────────────────────────────
    | int =>
      simp only [genSize] at hmem
      simp only [support_pick, support_bind, support_pure] at hmem
      rcases hmem with hleaf | hadd | hneg | hite
      · exact wellTypedAt_imp_isWellTyped env e
          (genLeaf_sound env .int e hleaf)
      · obtain ⟨a, ha, b, hb, rfl⟩ := hadd
        -- a, b come from genLeaf env .int = .lit (.int 0) only.
        exact wellTypedAt_imp_isWellTyped env (.binaryApp .add a b)
          (wellTypedAt_binaryApp_add_of_intLits env a b ha hb)
      · obtain ⟨a, ha, rfl⟩ := hneg
        -- a comes from genLeaf env .int = .lit (.int 0) only.
        exact wellTypedAt_imp_isWellTyped env (.unaryApp .neg a)
          (wellTypedAt_unaryApp_neg_of_intLit env a ha)
      · obtain ⟨c, hc, t, ht, f, hf, rfl⟩ := hite
        -- c comes from genLeaf env (.bool .anyBool) = bool literals only.
        have hc2 : Gen.support (genLeaf env (.bool .anyBool)) c := hc
        have ht2 : Gen.support (genLeaf env .int) t := ht
        have hf2 : Gen.support (genLeaf env .int) f := hf
        have hclit := genLeaf_boolAnyBool_is_lit env c hc2
        have ht'   := genLeaf_sound env .int t ht2
        have hf'   := genLeaf_sound env .int f hf2
        exact wellTypedAt_imp_isWellTyped env (.ite c t f)
          (wellTypedAt_ite_of_boolLit env c t f hclit ht' hf')
    -- ── .string ────────────────────────────────────────────────────
    | string =>
      simp only [genSize] at hmem
      exact wellTypedAt_imp_isWellTyped env e
        (genLeaf_sound env .string e hmem)
    -- ── .entity ────────────────────────────────────────────────────
    | entity ety =>
      simp only [genSize] at hmem
      simp only [support_pick, support_bind, support_pure] at hmem
      rcases hmem with hleaf | hite
      · exact wellTypedAt_imp_isWellTyped env e
          (genLeaf_sound env (.entity ety) e hleaf)
      · obtain ⟨c, hc, t, ht, f, hf, rfl⟩ := hite
        -- c comes from genSize env 0 (.bool .anyBool) = genLeaf env (.bool .anyBool)
        -- which only produces .lit (.bool true) or .lit (.bool false).
        -- Unfold fuel-0 genSize calls to genLeaf (definitionally equal).
        have hc2 : Gen.support (genLeaf env (.bool .anyBool)) c := hc
        have ht2 : Gen.support (genLeaf env (.entity ety)) t := ht
        have hf2 : Gen.support (genLeaf env (.entity ety)) f := hf
        have hclit := genLeaf_boolAnyBool_is_lit env c hc2
        have ht'   := genLeaf_sound env (.entity ety) t ht2
        have hf'   := genLeaf_sound env (.entity ety) f hf2
        exact wellTypedAt_imp_isWellTyped env (.ite c t f)
          (wellTypedAt_ite_of_boolLit env c t f hclit ht' hf')
    -- ── .set (Phase B, future work) ────────────────────────────────────
    | set ty =>
      simp only [genSize] at hmem
      exact wellTypedAt_imp_isWellTyped env e
        (genLeaf_sound env (.set ty) e hmem)
    -- ── .record (Phase B, future work) ─────────────────────────────────
    | record rty =>
      simp only [genSize] at hmem
      exact wellTypedAt_imp_isWellTyped env e
        (genLeaf_sound env (.record rty) e hmem)
    -- ── .ext (Phase B, future work) ────────────────────────────────────
    | ext xty =>
      simp only [genSize] at hmem
      exact wellTypedAt_imp_isWellTyped env e
        (genLeaf_sound env (.ext xty) e hmem)

-- ────────────────────────────────────────────────────────────────────
-- Step 5: the paper's main soundness theorem.
-- ────────────────────────────────────────────────────────────────────

/-- Every expression in the support of the hand-authored type-directed
    generator satisfies `CedarBridge.isWellTyped` at the requested
    environment. Fuel is fixed at 3. -/
theorem genWellTyped_sound (env : TypeEnv) (τ : CedarType) (e : Expr) :
    Gen.support (genWellTyped env τ) e → isWellTyped env e :=
  genSize_sound env 3 τ e

-- ────────────────────────────────────────────────────────────────────
-- §8 widening soundness lemmas.
--
-- Each helper in CedarFull.Expr (extDecimalLit, extIpLit,
-- setLitUserEntities, recordEmptyLit, recordSingletonLit) gets a
-- bottom-up `wellTypedAt env _ = true` lemma that PolicyGen uses
-- transitively when the helper is composed in a `when {}` body.
--
-- Proof status (V1 of §8 widening, ATH widen-genpolicy-extension-types):
--   • recordEmpty:       sorry-free
--   • recordSingleton:   sorry-free
--   • extDecimalLit:     sorry, deferred ATH-WIDEN-PROOF-EXT
--   • extIpLit:          sorry, deferred ATH-WIDEN-PROOF-EXT
--   • setLitUserEntities: sorry, deferred ATH-WIDEN-PROOF-SET
-- The two ext-type sorrys are blocked by Decimal.parse / IPAddr.parse
-- not kernel-reducing in Lean 4.29.1 (BitVec/Int64.ofInt? machinery).
-- The set sorry is blocked by typeOfSet's lub? fold needing schema-
-- conditioned reasoning — solvable but mechanically tedious.
-- ────────────────────────────────────────────────────────────────────

/-- Decimal literal `decimal("1.0")` typechecks at `(.ext .decimal)`.
    SORRY status: ATH-WIDEN-PROOF-EXT. -/
theorem wellTypedAt_extDecimalLit (env : TypeEnv) :
    wellTypedAt env extDecimalLit = true := by
  sorry

/-- IP literal `ip("10.0.0.1")` typechecks at `(.ext .ipAddr)`.
    SORRY status: ATH-WIDEN-PROOF-EXT. -/
theorem wellTypedAt_extIpLit (env : TypeEnv) :
    wellTypedAt env extIpLit = true := by
  sorry

/-- Empty record literal `{}` typechecks under any environment. -/
theorem wellTypedAt_recordEmpty (env : TypeEnv) :
    wellTypedAt env recordEmptyLit = true := by
  simp [wellTypedAt, recordEmptyLit, Cedar.Validation.typeOf,
        Cedar.Validation.ok, List.mapM₂, List.attach₂]

/-- Singleton record literal `{approved: true}` typechecks under any environment. -/
theorem wellTypedAt_recordSingleton (env : TypeEnv) :
    wellTypedAt env recordSingletonLit = true := by
  simp [wellTypedAt, recordSingletonLit, Cedar.Validation.typeOf,
        Cedar.Validation.typeOfLit, Cedar.Validation.ok, List.mapM₂,
        List.attach₂, Cedar.Data.Map.make, Except.map, Except.bind,
        Cedar.Data.Map.mk, Cedar.Validation.TypedExpr.typeOf]

/-- Set literal `[User::"alice", User::"bob", User::"carol"]` typechecks
    at `(.set (.entity User))`.  SORRY: ATH-WIDEN-PROOF-SET. -/
theorem wellTypedAt_setLitUserEntities_fixed
    (env : TypeEnv)
    (_hUser : env.ets.isValidEntityUID
              { ty := { id := "User", path := [] }, eid := "alice" } = true) :
    wellTypedAt env setLitUserEntities = true := by
  sorry

/-- ATH-617: single-element set literal `[User::"alice"]` typechecks
    at `(.set (.entity User))`. Same proof recipe as the 3-element
    case (typeOfSet on a non-empty homogeneous list); inherits the
    same SORRY: ATH-WIDEN-PROOF-SET deferral. -/
theorem wellTypedAt_setLitSingletonAlice
    (env : TypeEnv)
    (_hUser : env.ets.isValidEntityUID
              { ty := { id := "User", path := [] }, eid := "alice" } = true) :
    wellTypedAt env setLitSingletonAlice = true := by
  sorry

end CedarFull
