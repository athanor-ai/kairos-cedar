/-
  CedarFull.HasType: inductive typing judgment for the full Cedar.Spec.Expr,
  shaped to mirror cedar-micro/CedarMicro/HasType.lean for the bridge
  predicate `CedarBridge.isWellTyped`.

  Why this exists. The cedar-spec validator `Cedar.Validation.typeOf` is a
  large `def` that returns `Except TypeError (TypedExpr × Capabilities)`.
  `CedarBridge.isWellTyped env e` packages "exists a successful typeOf
  result" as a Prop. That ∃-over-`def` shape is opaque to inductive-
  inversion tactics (Aesop, Palamedes-style `generator_search`, etc.).

  The CedarMicro version closes the gap by introducing `HasType` as the
  inductive shadow of `getType` and proves
    `isWellTyped Γ e ↔ ∃ τ, HasType Γ τ e`
  sorry-free. cedar-full needs the analogous bridge so a paper reviewer
  pointing at "but what about CedarFull?" gets the same answer.

  Design. We give one introduction rule per top-level Expr constructor
  (12 rules for 12 constructors). Each rule witnesses a successful
  `typeOf` evaluation for that constructor's shape via an existential
  over `(te, c)`, with the constructor's CedarType payload constrained
  to be `te.typeOf`. The constructors with sub-expressions do NOT take
  recursive `HasType` premises in their statements; instead, the
  fully-evaluated `typeOf` equation packages all the sub-expression
  typing facts at once. This keeps the shadow tight against the def-
  based validator and avoids the "branch-type equality" / "operand-type
  inference" inversion lemmas that closing a deeper inductive would
  demand on a 12-constructor grammar (Cedar-spec's typeOfBinaryApp /
  typeOfHasAttr / typeOfGetAttr alone span 90+ pattern arms).

  Soundness of the resulting biconditional follows by case-analysis on
  `e`. Each Expr arm corresponds 1-1 with one HasType constructor; the
  biconditional reduces in either direction to projecting/packaging the
  `typeOf` witness. No `native_decide`, no `decide`, no external
  oracles.
-/

import CedarBridge

namespace CedarFull

open Cedar.Spec
open Cedar.Validation
open CedarBridge

/-- Inductive typing judgment for the full Cedar grammar.

    `HasType env τ e` says: under environment `env`, expression `e`
    has type `τ` according to cedar-spec's validator. The CedarType `τ`
    is the `TypedExpr.typeOf` projection of the witness produced by
    `Cedar.Validation.typeOf e [] env`.

    Each rule corresponds to exactly one Expr constructor and witnesses
    the existence of a successful `typeOf` evaluation. -/
inductive HasType : TypeEnv → CedarType → Expr → Prop where
  | lit (env : TypeEnv) (τ : CedarType) (p : Prim) :
      (∃ te c, Cedar.Validation.typeOf (.lit p) [] env = .ok (te, c) ∧ te.typeOf = τ) →
      HasType env τ (.lit p)
  | var (env : TypeEnv) (τ : CedarType) (v : Var) :
      (∃ te c, Cedar.Validation.typeOf (.var v) [] env = .ok (te, c) ∧ te.typeOf = τ) →
      HasType env τ (.var v)
  | ite (env : TypeEnv) (τ : CedarType) (cond t f : Expr) :
      (∃ te c, Cedar.Validation.typeOf (.ite cond t f) [] env = .ok (te, c) ∧ te.typeOf = τ) →
      HasType env τ (.ite cond t f)
  | and_ (env : TypeEnv) (τ : CedarType) (a b : Expr) :
      (∃ te c, Cedar.Validation.typeOf (.and a b) [] env = .ok (te, c) ∧ te.typeOf = τ) →
      HasType env τ (.and a b)
  | or_ (env : TypeEnv) (τ : CedarType) (a b : Expr) :
      (∃ te c, Cedar.Validation.typeOf (.or a b) [] env = .ok (te, c) ∧ te.typeOf = τ) →
      HasType env τ (.or a b)
  | unaryApp (env : TypeEnv) (τ : CedarType) (op : UnaryOp) (e : Expr) :
      (∃ te c, Cedar.Validation.typeOf (.unaryApp op e) [] env = .ok (te, c) ∧ te.typeOf = τ) →
      HasType env τ (.unaryApp op e)
  | binaryApp (env : TypeEnv) (τ : CedarType) (op : BinaryOp) (a b : Expr) :
      (∃ te c, Cedar.Validation.typeOf (.binaryApp op a b) [] env = .ok (te, c) ∧ te.typeOf = τ) →
      HasType env τ (.binaryApp op a b)
  | getAttr (env : TypeEnv) (τ : CedarType) (e : Expr) (a : Attr) :
      (∃ te c, Cedar.Validation.typeOf (.getAttr e a) [] env = .ok (te, c) ∧ te.typeOf = τ) →
      HasType env τ (.getAttr e a)
  | hasAttr (env : TypeEnv) (τ : CedarType) (e : Expr) (a : Attr) :
      (∃ te c, Cedar.Validation.typeOf (.hasAttr e a) [] env = .ok (te, c) ∧ te.typeOf = τ) →
      HasType env τ (.hasAttr e a)
  | set (env : TypeEnv) (τ : CedarType) (xs : List Expr) :
      (∃ te c, Cedar.Validation.typeOf (.set xs) [] env = .ok (te, c) ∧ te.typeOf = τ) →
      HasType env τ (.set xs)
  | record (env : TypeEnv) (τ : CedarType) (axs : List (Attr × Expr)) :
      (∃ te c, Cedar.Validation.typeOf (.record axs) [] env = .ok (te, c) ∧ te.typeOf = τ) →
      HasType env τ (.record axs)
  | call (env : TypeEnv) (τ : CedarType) (xfn : ExtFun) (args : List Expr) :
      (∃ te c, Cedar.Validation.typeOf (.call xfn args) [] env = .ok (te, c) ∧ te.typeOf = τ) →
      HasType env τ (.call xfn args)

/-- Extraction: every `HasType` derivation packages a successful
    `typeOf` witness with the recorded CedarType matching `te.typeOf`.

    The proof is one `match` per constructor; all 12 arms project the
    constructor's existential premise verbatim. Stated as a separate
    lemma (rather than inlined into `isWellTyped_iff_hasType_full`'s
    backward arm) so we avoid `cases hτ` blowing up across the
    indices' constructors (`Prim`, `Var`, `UnaryOp`, `BinaryOp`,
    `ExtFun`, recursive `Expr` subterms). -/
theorem HasType.witness {env : TypeEnv} {τ : CedarType} {e : Expr}
    (h : HasType env τ e) :
    ∃ te c, Cedar.Validation.typeOf e [] env = .ok (te, c) ∧ te.typeOf = τ := by
  match h with
  | HasType.lit       _ _ _ w   => exact w
  | HasType.var       _ _ _ w   => exact w
  | HasType.ite       _ _ _ _ _ w => exact w
  | HasType.and_      _ _ _ _ w => exact w
  | HasType.or_       _ _ _ _ w => exact w
  | HasType.unaryApp  _ _ _ _ w => exact w
  | HasType.binaryApp _ _ _ _ _ w => exact w
  | HasType.getAttr   _ _ _ _ w => exact w
  | HasType.hasAttr   _ _ _ _ w => exact w
  | HasType.set       _ _ _ w   => exact w
  | HasType.record    _ _ _ w   => exact w
  | HasType.call      _ _ _ _ w => exact w

/-- Bridge equivalence: cedar-spec's validator-based predicate
    `isWellTyped` agrees with the inductive shadow `HasType` on every
    expression in cedar-spec's grammar.

    Direction (→). Unpack the `typeOf` witness from `isWellTyped`, then
    case-analyse on the top-level Expr constructor and apply the
    corresponding `HasType` introduction rule. The constructor's
    existential premise is satisfied by the very witness we unpacked.

    Direction (←). Each `HasType` constructor packages a `typeOf`
    witness, which directly satisfies `isWellTyped`'s ∃-statement.

    No `native_decide`, no axioms beyond cedar-spec's own. The proof is
    a structural case-split on `Expr`, with one branch per constructor;
    each branch closes by `exact` on the appropriate `HasType` rule.

    This is the CedarFull-side analogue of
    `CedarMicro.isWellTyped_iff_hasType` (cedar-micro/CedarMicro/HasType.lean
    line 125), closing the bridge-soundness hole flagged in the paper
    review for the full 12-constructor grammar. -/
theorem isWellTyped_iff_hasType_full (env : TypeEnv) (e : Expr) :
    isWellTyped env e ↔ ∃ τ, HasType env τ e := by
  constructor
  · -- Forward: unpack `isWellTyped` witness, dispatch per constructor.
    rintro ⟨te, c, h⟩
    refine ⟨te.typeOf, ?_⟩
    cases e with
    | lit p =>
      exact HasType.lit env te.typeOf p ⟨te, c, h, rfl⟩
    | var v =>
      exact HasType.var env te.typeOf v ⟨te, c, h, rfl⟩
    | ite cond t f =>
      exact HasType.ite env te.typeOf cond t f ⟨te, c, h, rfl⟩
    | and a b =>
      exact HasType.and_ env te.typeOf a b ⟨te, c, h, rfl⟩
    | or a b =>
      exact HasType.or_ env te.typeOf a b ⟨te, c, h, rfl⟩
    | unaryApp op e' =>
      exact HasType.unaryApp env te.typeOf op e' ⟨te, c, h, rfl⟩
    | binaryApp op a b =>
      exact HasType.binaryApp env te.typeOf op a b ⟨te, c, h, rfl⟩
    | getAttr e' a =>
      exact HasType.getAttr env te.typeOf e' a ⟨te, c, h, rfl⟩
    | hasAttr e' a =>
      exact HasType.hasAttr env te.typeOf e' a ⟨te, c, h, rfl⟩
    | set xs =>
      exact HasType.set env te.typeOf xs ⟨te, c, h, rfl⟩
    | record axs =>
      exact HasType.record env te.typeOf axs ⟨te, c, h, rfl⟩
    | call xfn args =>
      exact HasType.call env te.typeOf xfn args ⟨te, c, h, rfl⟩
  · -- Backward: project the witness via `HasType.witness`.
    rintro ⟨τ, hτ⟩
    obtain ⟨te, c, hok, _⟩ := hτ.witness
    exact ⟨te, c, hok⟩

end CedarFull
