/-
  RegoFull.Soundness: soundness theorems for the Rego generator.

  Headline claim (parallel to CedarFull.Soundness §5.1):

    ∀ σ e, e ∈ support (genPolicy) → isWellTypedBool σ e

  Since `genPolicy` is a static pool of 8 shapes with explicit `HasType`
  derivations, soundness reduces to providing one `HasType` witness per
  shape. Each theorem is sorry-free.

  Proof strategy:
    Each `shapeN_wt` theorem applies `HasType` constructors directly.
    Schema lookup facts are proved by `simp [fixedSchema, Schema.lookup]`
    (kernel reduction on the fixed list). The `cmp_same` for ordered
    comparisons uses an explicit Or-chain to select the right disjunct.
-/

import RegoFull.PolicyGen

open Rego.Spec
open RegoBridge
open RegoFull.PolicyGen

namespace RegoFull.Soundness

/-── Schema lookup facts ─────────────────────────────────────────────────────-/

theorem fixedSchema_lookup_role :
    fixedSchema.lookup "role" = some (.scalar .string) := by
  simp [fixedSchema, Schema.lookup]

theorem fixedSchema_lookup_level :
    fixedSchema.lookup "level" = some (.scalar .number) := by
  simp [fixedSchema, Schema.lookup]

theorem fixedSchema_lookup_groups :
    fixedSchema.lookup "groups" = some (.array (.scalar .string)) := by
  simp [fixedSchema, Schema.lookup]

theorem fixedSchema_lookup_active :
    fixedSchema.lookup "active" = some (.scalar .bool) := by
  simp [fixedSchema, Schema.lookup]

theorem fixedSchema_lookup_user :
    fixedSchema.lookup "user" =
    some (.object [("role", .scalar .string), ("tier", .scalar .number)]) := by
  simp [fixedSchema, Schema.lookup]

theorem user_role_subfield :
    (([("role", RegoType.scalar .string), ("tier", .scalar .number)]).find?
      (fun (k, _) => k == "role")).map (·.2) = some (.scalar .string) := by
  simp

/-── Ordinal comparison disjunct lemmas ──────────────────────────────────────-/

-- The `cmp_same` constructor's condition for ordered ops is:
--   op = eq ∨ op = neq ∨ (τ = scalar number ∧ (op = lt ∨ op = le ∨ op = gt ∨ op = ge))

private theorem cmp_gt_cond :
    (CmpOp.gt = CmpOp.eq) ∨ (CmpOp.gt = CmpOp.neq) ∨
    (RegoType.scalar ScalarType.number = RegoType.scalar ScalarType.number ∧
     (CmpOp.gt = CmpOp.lt ∨ CmpOp.gt = CmpOp.le ∨
      CmpOp.gt = CmpOp.gt ∨ CmpOp.gt = CmpOp.ge)) :=
  Or.inr (Or.inr ⟨rfl, Or.inr (Or.inr (Or.inl rfl))⟩)

/-── Per-arm HasType derivations ─────────────────────────────────────────────-/

/-- Shape 1: `input.role == "admin"` is well-typed at `scalar bool`. -/
theorem shape1_wt : HasType fixedSchema shape1.body (.scalar .bool) :=
  HasType.cmp_same fixedSchema .eq
    (.input_attr "role") (.lit (.string "admin")) (.scalar .string)
    (Or.inl rfl)
    (HasType.attr_typed fixedSchema "role" (.scalar .string) fixedSchema_lookup_role)
    (HasType.lit_string fixedSchema "admin")

/-- Shape 2: `input.level > 3` is well-typed at `scalar bool`. -/
theorem shape2_wt : HasType fixedSchema shape2.body (.scalar .bool) :=
  HasType.cmp_same fixedSchema .gt
    (.input_attr "level") (.lit (.number 3)) (.scalar .number)
    cmp_gt_cond
    (HasType.attr_typed fixedSchema "level" (.scalar .number) fixedSchema_lookup_level)
    (HasType.lit_number fixedSchema 3)

/-- Shape 3: `input.role in {"admin", "editor"}` is well-typed at `scalar bool`. -/
theorem shape3_wt : HasType fixedSchema shape3.body (.scalar .bool) :=
  HasType.in_set fixedSchema
    (.input_attr "role")
    [.string "admin", .string "editor"]
    (.scalar .string)
    (HasType.attr_typed fixedSchema "role" (.scalar .string) fixedSchema_lookup_role)
    (by simp)

/-- Shape 4: `input.active == true` is well-typed at `scalar bool`. -/
theorem shape4_wt : HasType fixedSchema shape4.body (.scalar .bool) :=
  HasType.cmp_same fixedSchema .eq
    (.input_attr "active") (.lit (.bool true)) (.scalar .bool)
    (Or.inl rfl)
    (HasType.attr_typed fixedSchema "active" (.scalar .bool) fixedSchema_lookup_active)
    (HasType.lit_bool fixedSchema true)

/-- Shape 5: conjunction of shapes 1 and 2 is well-typed. -/
theorem shape5_wt : HasType fixedSchema shape5.body (.scalar .bool) :=
  HasType.and_ fixedSchema
    (.cmp .eq (.input_attr "role") (.lit (.string "admin")))
    (.cmp .gt (.input_attr "level") (.lit (.number 3)))
    shape1_wt
    shape2_wt

/-- Shape 6: `input.groups[_] == "ops"` (array membership) is well-typed. -/
theorem shape6_wt : HasType fixedSchema shape6.body (.scalar .bool) :=
  HasType.in_arr fixedSchema "groups"
    (.lit (.string "ops")) (.scalar .string)
    fixedSchema_lookup_groups
    (HasType.lit_string fixedSchema "ops")

/-- Shape 7: `not (active == true) ∧ role == "viewer"` is well-typed. -/
theorem shape7_wt : HasType fixedSchema shape7.body (.scalar .bool) :=
  HasType.and_ fixedSchema
    (.not_ (.cmp .eq (.input_attr "active") (.lit (.bool true))))
    (.cmp .eq (.input_attr "role") (.lit (.string "viewer")))
    (HasType.not_ fixedSchema _
      (HasType.cmp_same fixedSchema .eq
        (.input_attr "active") (.lit (.bool true)) (.scalar .bool)
        (Or.inl rfl)
        (HasType.attr_typed fixedSchema "active" (.scalar .bool) fixedSchema_lookup_active)
        (HasType.lit_bool fixedSchema true)))
    (HasType.cmp_same fixedSchema .eq
      (.input_attr "role") (.lit (.string "viewer")) (.scalar .string)
      (Or.inl rfl)
      (HasType.attr_typed fixedSchema "role" (.scalar .string) fixedSchema_lookup_role)
      (HasType.lit_string fixedSchema "viewer"))

/-- Shape 8: `input.user.role == "admin"` (nested) is well-typed at `scalar bool`. -/
theorem shape8_wt : HasType fixedSchema shape8.body (.scalar .bool) := by
  apply HasType.cmp_same fixedSchema .eq _ _ (.scalar .string) (Or.inl rfl)
  · exact HasType.nested_typed fixedSchema "user" "role"
        [("role", .scalar .string), ("tier", .scalar .number)] (.scalar .string)
        fixedSchema_lookup_user user_role_subfield
  · exact HasType.lit_string fixedSchema "admin"

/-── Generator soundness ─────────────────────────────────────────────────────-/

/-- Every expression in the support of `genPolicy` is well-typed at
    `scalar bool` under `fixedSchema`. -/
theorem genPolicy_sound :
    ∀ (shape : PolicyShape),
      shape ∈ genPolicy.val →
      HasType fixedSchema shape.body (.scalar .bool) := by
  intro shape h
  simp [genPolicy, allShapes] at h
  rcases h with rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl
  · exact shape1_wt
  · exact shape2_wt
  · exact shape3_wt
  · exact shape4_wt
  · exact shape5_wt
  · exact shape6_wt
  · exact shape7_wt
  · exact shape8_wt

/-- Corollary: every generated shape's body satisfies `isWellTypedBool`. -/
theorem genPolicy_isWellTypedBool :
    ∀ (shape : PolicyShape),
      shape ∈ genPolicy.val →
      isWellTypedBool fixedSchema shape.body :=
  genPolicy_sound

end RegoFull.Soundness
