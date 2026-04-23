import Palamedes.Gen
import CedarMicro.Ty
import CedarMicro.Expr

open CedarMicro

def varIndices (Γ : List Ty) (τ : Ty) : List Nat :=
  let rec loop (i : Nat) (rest : List Ty) (acc : List Nat) : List Nat :=
    match rest with
    | [] => acc.reverse
    | t :: ts => loop (i + 1) ts (if t == τ then i :: acc else acc)
  loop 0 Γ []

def pickFromList (default : α) (xs : List α) : Gen α :=
  match xs with
  | [] => pure default
  | [x] => pure x
  | x :: y :: ys =>
      let n := xs.length / 2
      Gen.pick (pickFromList default (xs.take n)) (pickFromList default (xs.drop n))
termination_by xs.length
decreasing_by
  simp_wf
  · -- take decreases
    rw [List.length_take]
    have h1 : xs.length ≥ 2 := by simp [List.length]; omega
    have h2 : xs.length / 2 < xs.length := by
      apply Nat.div_lt_self
      omega
      decide
    have h3 : min (xs.length / 2) xs.length = xs.length / 2 := by
      apply Nat.min_eq_left
      omega
    rw [h3]
    omega
  · -- drop decreases
    rw [List.length_drop]
    have h1 : xs.length ≥ 2 := by simp [List.length]; omega
    have h2 : xs.length / 2 > 0 := by omega
    omega

def genLeaf (Γ : List Ty) (τ : Ty) : Gen Expr :=
  match τ with
  | .int =>
      let literals := [Expr.litInt 0, Expr.litInt 1, Expr.litInt (-1), Expr.litInt 2, Expr.litInt 42]
      let vars := (varIndices Γ .int).map Expr.var
      let litGen := pickFromList (Expr.litInt 0) literals
      if vars.isEmpty then litGen else Gen.pick litGen (pickFromList (Expr.litInt 0) vars)
  | .bool =>
      let literals := [Expr.litBool true, Expr.litBool false]
      let vars := (varIndices Γ .bool).map Expr.var
      let litGen := pickFromList (Expr.litBool true) literals
      if vars.isEmpty then litGen else Gen.pick litGen (pickFromList (Expr.litBool true) vars)

def genWellTypedFuel (fuel : Nat) (Γ : List Ty) (τ : Ty) : Gen Expr :=
  match fuel with
  | 0 => genLeaf Γ τ
  | fuel + 1 =>
      match τ with
      | .int =>
          let node := do
            let c ← genWellTypedFuel fuel Γ .bool
            let t ← genWellTypedFuel fuel Γ .int
            let f ← genWellTypedFuel fuel Γ .int
            pure (Expr.ite c t f)
          Gen.pick (genLeaf Γ .int) node
      | .bool =>
          let iteNode := do
            let c ← genWellTypedFuel fuel Γ .bool
            let t ← genWellTypedFuel fuel Γ .bool
            let f ← genWellTypedFuel fuel Γ .bool
            pure (Expr.ite c t f)
          let andNode := do
            let a ← genWellTypedFuel fuel Γ .bool
            let b ← genWellTypedFuel fuel Γ .bool
            pure (Expr.and a b)
          let node := Gen.pick iteNode andNode
          Gen.pick (genLeaf Γ .bool) node

def genWellTyped (Γ : List Ty) (τ : Ty) : Gen Expr :=
  genWellTypedFuel 4 Γ τ