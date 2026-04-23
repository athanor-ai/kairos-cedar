import CedarMicro.Ty
import CedarMicro.Expr
import Palamedes.Gen

open CedarMicro

def matchingVars (Γ : List Ty) (τ : Ty) : List Nat :=
  List.range Γ.length |>.filter (fun i =>
    match Γ.get? i with
    | some t => t == τ
    | none => false
  )

def pickFromList {α : Type} (xs : List α) (default : α) : Gen α :=
  match xs with
  | [] => Gen.pure default
  | x :: xs => xs.foldl (fun acc y => Gen.pick acc (Gen.pure y)) (Gen.pure x)

def genLitInt : Gen Expr :=
  Gen.pick (Gen.pure (Expr.litInt 0))
    (Gen.pick (Gen.pure (Expr.litInt 1))
      (Gen.pure (Expr.litInt (-1))))

def genLitBool : Gen Expr :=
  Gen.pick (Gen.pure (Expr.litBool true))
    (Gen.pure (Expr.litBool false))

def genLeaf (Γ : List Ty) (τ : Ty) : Gen Expr :=
  let vars := matchingVars Γ τ
  match τ with
  | .int =>
    let varGen := pickFromList (vars.map Expr.var) (Expr.litInt 0)
    if vars.isEmpty then genLitInt else Gen.pick genLitInt varGen
  | .bool =>
    let varGen := pickFromList (vars.map Expr.var) (Expr.litBool true)
    if vars.isEmpty then genLitBool else Gen.pick genLitBool varGen

def genAnd (recGen : (τ : Ty) → Gen Expr) : Gen Expr := do
  let a ← recGen .bool
  let b ← recGen .bool
  pure (Expr.and a b)

def genIte (recGen : (τ : Ty) → Gen Expr) (τ : Ty) : Gen Expr := do
  let c ← recGen .bool
  let t ← recGen τ
  let f ← recGen τ
  pure (Expr.ite c t f)

def genWellTypedFuel (fuel : Nat) (Γ : List Ty) (τ : Ty) : Gen Expr :=
  match fuel with
  | 0 => genLeaf Γ τ
  | n+1 =>
    let recGen := genWellTypedFuel n Γ
    match τ with
    | .bool =>
      Gen.pick (Gen.pick (genLeaf Γ .bool) (genAnd recGen))
        (Gen.pick (genIte recGen .bool) (genLeaf Γ .bool))
    | .int =>
      Gen.pick (Gen.pick (genLeaf Γ .int) (genIte recGen .int))
        (Gen.pick (genLeaf Γ .int) (genIte recGen .int))

def genWellTyped (Γ : List Ty) (τ : Ty) : Gen Expr :=
  genWellTypedFuel 4 Γ τ