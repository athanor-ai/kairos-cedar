/-
  RegoBridge.Spec.Eval: a small evaluator for the Rego subset.

  Design: Rego's undefined/false distinction is preserved via an `Option Bool`
  result type:
    - `some true`  = the rule fired with value true
    - `some false` = the expression reduced to false (not undefined)
    - `none`       = the expression is undefined (e.g. attribute missing from input)

  This matches OPA's documented semantics: an undefined decision is not the
  same as `false`. Our pipeline checks whether OPA's `opa eval` result for
  a generated policy + input agrees with this evaluator.

  Note: the evaluator is intentionally simple. Disagreements between this
  evaluator and OPA's reference implementation are the primary bug-finding
  signal.
-/

import RegoBridge.Spec.Expr

namespace Rego.Spec

/-── Input document ─────────────────────────────────────────────────────────-/

/-- A Rego value (the evaluated form of an expression). -/
inductive Value
  | bool   : Bool   → Value
  | number : Int    → Value
  | string : String → Value
  | null   : Value
  | array  : List Value → Value
  | set_   : List Value → Value      -- treated as unordered (bag semantics for eval)
  | object : List (String × Value) → Value
  deriving Repr

/-- BEq for Value (structural, depth-first). -/
partial def Value.beq : Value → Value → Bool
  | .bool a, .bool b     => a == b
  | .number a, .number b => a == b
  | .string a, .string b => a == b
  | .null, .null         => true
  | .array a, .array b   =>
    a.length == b.length && (a.zip b).all (fun (x, y) => Value.beq x y)
  | .set_ a, .set_ b     =>
    a.length == b.length && (a.zip b).all (fun (x, y) => Value.beq x y)
  | .object a, .object b =>
    a.length == b.length &&
    (a.zip b).all (fun ((k1, v1), (k2, v2)) => k1 == k2 && Value.beq v1 v2)
  | _, _ => false

instance : BEq Value := ⟨Value.beq⟩

/-- An input document is a key-value map (top-level object). -/
abbrev Input := List (String × Value)

/-- Look up a key in an input document. -/
def Input.lookup (inp : Input) (key : String) : Option Value :=
  (inp.find? (fun (k, _) => k == key)).map (·.2)

/-── Literal evaluation ─────────────────────────────────────────────────────-/

def evalLit : Literal → Value
  | .bool b   => .bool b
  | .number n => .number n
  | .string s => .string s
  | .null     => .null

/-── Comparison ─────────────────────────────────────────────────────────────-/

def evalCmp (op : CmpOp) (v1 v2 : Value) : Option Bool :=
  match op with
  | .eq  => some (v1 == v2)
  | .neq => some (v1 != v2)
  | .lt  => match v1, v2 with
              | .number a, .number b => some (a < b)
              | _, _ => none    -- type mismatch → undefined
  | .le  => match v1, v2 with
              | .number a, .number b => some (a ≤ b)
              | _, _ => none
  | .gt  => match v1, v2 with
              | .number a, .number b => some (a > b)
              | _, _ => none
  | .ge  => match v1, v2 with
              | .number a, .number b => some (a ≥ b)
              | _, _ => none

/-── Main evaluator ─────────────────────────────────────────────────────────-/

/-- Evaluate a Rego expression against an input document.
    Returns `none` for undefined, `some b` for a boolean result.

    NOTE: This evaluator only handles expressions whose result type is
    `scalar bool` (i.e. well-typed policy bodies). For the bridge's
    generator, all expressions are generated to have bool type at the top
    level, so the `none` case from evalCmp covers only ill-typed or
    undefined situations that OPA itself would also treat as undefined. -/
def eval (inp : Input) : Expr → Option Bool
  | .lit (.bool b)   => some b
  | .lit _           => none     -- non-bool literal at top level → undefined

  | .input_attr key  =>
    match inp.lookup key with
    | some (Value.bool b) => some b
    | some _              => none     -- attribute exists but is not bool
    | none                => none     -- attribute missing → undefined

  | .nested key sub  =>
    match inp.lookup key with
    | some (Value.object kvs) =>
      match (kvs.find? (fun (k, _) => k == sub)).map (·.2) with
      | some (Value.bool b) => some b
      | some _              => none
      | none                => none
    | _ => none

  | .cmp op e1 e2    =>
    -- Evaluate both sides to values (not necessarily bool)
    let v1 := evalToValue inp e1
    let v2 := evalToValue inp e2
    match v1, v2 with
    | some v1', some v2' => evalCmp op v1' v2'
    | _, _               => none

  | .in_set e vs     =>
    match evalToValue inp e with
    | some v => some (vs.any (fun lit => evalLit lit == v))
    | none   => none

  | .in_arr key e2   =>
    match inp.lookup key with
    | some (.array elems) =>
      match evalToValue inp e2 with
      | some v => some (elems.any (· == v))
      | none   => none
    | _ => none

  | .and_ e1 e2      =>
    match eval inp e1 with
    | some true  => eval inp e2
    | some false => some false
    | none       => none

  | .or_ e1 e2       =>
    match eval inp e1 with
    | some true  => some true
    | some false => eval inp e2
    | none       =>
      -- In Rego, if one branch is undefined the other can still succeed.
      -- We model this as: if e2 succeeds, return that; else none.
      eval inp e2

  | .not_ e          =>
    match eval inp e with
    | some b => some (!b)
    | none   => none             -- `not undefined` is also undefined in spec

where
  /-- Evaluate an expression to any Value (not just Bool).
      Used by comparison and membership sub-expressions. -/
  evalToValue (inp : Input) : Expr → Option Value
    | .lit l           => some (evalLit l)
    | .input_attr key  => inp.lookup key
    | .nested key sub  =>
      match inp.lookup key with
      | some (.object kvs) => (kvs.find? (fun (k, _) => k == sub)).map (·.2)
      | _ => none
    | .cmp op e1 e2    =>
      let v1 := evalToValue inp e1
      let v2 := evalToValue inp e2
      match v1, v2 with
      | some v1', some v2' =>
        (evalCmp op v1' v2').map .bool
      | _, _ => none
    | .in_set e vs     =>
      match evalToValue inp e with
      | some v => some (.bool (vs.any (fun l => evalLit l == v)))
      | none   => none
    | .in_arr key e2   =>
      match inp.lookup key with
      | some (.array elems) =>
        match evalToValue inp e2 with
        | some v => some (.bool (elems.any (· == v)))
        | none   => none
      | _ => none
    | .and_ e1 e2      =>
      match eval inp e1 with
      | some true  => evalToValue inp e2
      | some false => some (.bool false)
      | none       => none
    | .or_ e1 e2       =>
      match eval inp e1 with
      | some true  => some (.bool true)
      | some false => evalToValue inp e2
      | none       => evalToValue inp e2
    | .not_ e          =>
      match eval inp e with
      | some b => some (.bool (!b))
      | none   => none

end Rego.Spec
