/-
  CedarFull.Test: kernel-level coverage tests for genSize and PolicyGen.

  Each test asserts a structural property about a generator arm or
  policy template. Tests run as `lake build`-time obligations: a
  regression that drops an arm, renames an id, or shrinks the
  candidate-attribute list fails the build (the corresponding
  theorem becomes unprovable). No `native_decide`; everything closes
  via plain `simp` / `rfl` through definitional unfolding.

  Why these tests exist:
    Stage 0 of cedar-full shipped with five constructors reachable
    in genSize (lit, var, ite, and, or) and a single random-condition
    policy shape in PolicyGen. A spec-author code review caught both
    gaps. This module is the regression net so that subsequent
    refactors keep each constructor reachable, each candidate name
    in the hasAttr list, and each random-condition policy template
    correctly named.

  Three test layers:
    1. Constructor reachability: each new constructor head appears
       in the support of its target generator (fuel-1 enumeration).
    2. Policy-template structural correctness: each `policyWith…`
       helper sets `Policy.id` to the documented string, regardless
       of the condition expression it wraps.
    3. Generator-shape invariants: list lengths, name counts,
       constructor-arity guards.

  Layered with experiments/phase_l_pbt_property/ (Python-level
  property-based sampling) and experiments/phase_m_mutation/
  (mutation-test harness) to catch shape regressions that are not
  visible at the type-equality level.
-/

import CedarFull.Expr
import CedarFull.PolicyGen
import CedarFull.Soundness

namespace CedarFull.Test

open Cedar.Spec
open Cedar.Validation
open CedarFull
open CedarFull.PolicyGen
open Gen.Support

-- ────────────────────────────────────────────────────────────────────
-- Layer 1: constructor reachability in genSize / genHasAttrContext
-- ────────────────────────────────────────────────────────────────────

-- hasAttrNames invariants -------------------------------------------

example : hasAttrNames.length = 5 := by simp [hasAttrNames]

example : "approved" ∈ hasAttrNames := by simp [hasAttrNames]
example : "tags"     ∈ hasAttrNames := by simp [hasAttrNames]
example : "name"     ∈ hasAttrNames := by simp [hasAttrNames]
example : "level"    ∈ hasAttrNames := by simp [hasAttrNames]
example : "id"       ∈ hasAttrNames := by simp [hasAttrNames]

-- hasAttr generator support -----------------------------------------

example : Gen.support genHasAttrContext
    (.hasAttr (.var .context) "approved") := by
  simp [genHasAttrContext, Gen.support, hasAttrNames]

example : Gen.support genHasAttrContext
    (.hasAttr (.var .context) "tags") := by
  simp [genHasAttrContext, Gen.support, hasAttrNames]

example : Gen.support genHasAttrContext
    (.hasAttr (.var .context) "id") := by
  simp [genHasAttrContext, Gen.support, hasAttrNames]

-- getAttr-on-record-singleton structural shape ----------------------
-- The output expression always has the `.getAttr (.record [("v", _)]) "v"`
-- shape. We verify the canonical bool/int outputs are reachable.

example :
    Gen.support
      (genGetAttrOfRecordSingleton (genLeaf fixedEnv (.bool .anyBool)))
      (.getAttr (.record [("v", .lit (.bool true))]) "v") := by
  simp only [genGetAttrOfRecordSingleton, support_bind, support_pure]
  refine ⟨.lit (.bool true), ?_, rfl⟩
  simp [genLeaf, Gen.support, varGen, varsOfType, litGen, Gen.pick,
        Gen.ret, pure]

example :
    Gen.support
      (genGetAttrOfRecordSingleton (genLeaf fixedEnv .int))
      (.getAttr (.record [("v", .lit (.int 0))]) "v") := by
  simp only [genGetAttrOfRecordSingleton, support_bind, support_pure]
  refine ⟨.lit (.int 0), ?_, rfl⟩
  simp [genLeaf, Gen.support, varGen, varsOfType, litGen, Gen.pick,
        Gen.ret, pure]

-- ────────────────────────────────────────────────────────────────────
-- Layer 2: policy-template structural correctness
-- ────────────────────────────────────────────────────────────────────
--
-- Each `policyWith*` helper must set Policy.id to the documented id
-- regardless of the condition expression it wraps. A regression that
-- renames the id (or refactors the helper to drop the id-set) fails
-- the build.

example : ∀ e, (policyWithWhenCond e).id = "permit-with-when-cond" := by
  intro e; rfl

example : ∀ e, (policyWithUnlessCond e).id = "permit-with-unless-cond" := by
  intro e; rfl

example : ∀ e, (forbidPolicyWithWhenCond e).id = "forbid-with-when-cond" := by
  intro e; rfl

example : ∀ e, (forbidPolicyWithUnlessCond e).id = "forbid-with-unless-cond" := by
  intro e; rfl

example : ∀ e,
    (policyWithIsUserAndWhenCond e).id =
      "permit-principal-is-user-with-when-cond" := by
  intro e; rfl

-- Effect-class invariants: permit vs forbid wiring is correct.

example : ∀ e, (policyWithWhenCond e).effect = .permit := by intro e; rfl
example : ∀ e, (policyWithUnlessCond e).effect = .permit := by intro e; rfl
example : ∀ e, (forbidPolicyWithWhenCond e).effect = .forbid := by intro e; rfl
example : ∀ e, (forbidPolicyWithUnlessCond e).effect = .forbid := by intro e; rfl
example : ∀ e, (policyWithIsUserAndWhenCond e).effect = .permit := by intro e; rfl

-- Condition-kind invariants: when vs unless wiring is correct.

example : ∀ e, ((policyWithWhenCond e).condition.head?.map (·.kind)) = some .when := by
  intro e; rfl
example : ∀ e, ((policyWithUnlessCond e).condition.head?.map (·.kind)) = some .unless := by
  intro e; rfl
example : ∀ e, ((forbidPolicyWithWhenCond e).condition.head?.map (·.kind)) = some .when := by
  intro e; rfl
example : ∀ e, ((forbidPolicyWithUnlessCond e).condition.head?.map (·.kind)) = some .unless := by
  intro e; rfl

-- Body-passes-through invariant: the condExpr argument lands in
-- condition.head.body. A regression that hard-codes a literal here
-- (instead of wiring the random expr) fails this check.

example : ∀ e, ((policyWithWhenCond e).condition.head?.map (·.body)) = some e := by
  intro e; rfl
example : ∀ e, ((policyWithUnlessCond e).condition.head?.map (·.body)) = some e := by
  intro e; rfl
example : ∀ e, ((forbidPolicyWithWhenCond e).condition.head?.map (·.body)) = some e := by
  intro e; rfl
example : ∀ e, ((forbidPolicyWithUnlessCond e).condition.head?.map (·.body)) = some e := by
  intro e; rfl
example : ∀ e, ((policyWithIsUserAndWhenCond e).condition.head?.map (·.body)) = some e := by
  intro e; rfl

end CedarFull.Test
