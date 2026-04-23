# Initial prompt for LLM-synthesised Cedar-micro generator

You are writing Lean 4 code for a property-based testing library. Your task is to synthesise a random generator for well-typed expressions in a small typed lambda-calculus-adjacent language. The generator must, by construction, produce only expressions that satisfy a given typing predicate.

## Target language (`CedarMicro`)

A simplified subset of the Cedar policy language, suitable for a property-based testing proof of concept:

```lean
inductive Ty : Type where
  | bool
  | int

inductive Expr : Type where
  | litInt  : Int → Expr
  | litBool : Bool → Expr
  | var     : Nat → Expr
  | ite     : Expr → Expr → Expr → Expr
  | and     : Expr → Expr → Expr
```

## Typing spec (the oracle)

```lean
@[simp]
def getType (e : Expr) (Γ : List Ty) : Option Ty :=
  match e with
  | .litInt _  => pure .int
  | .litBool _ => pure .bool
  | .var n     => Γ[n]?
  | .ite c t f => do
    let τc ← getType c Γ
    let τt ← getType t Γ
    let τf ← getType f Γ
    guard (τc == Ty.bool)
    guard (τt == τf)
    pure τt
  | .and a b => do
    let τa ← getType a Γ
    let τb ← getType b Γ
    guard (τa == Ty.bool)
    guard (τb == Ty.bool)
    pure Ty.bool

def wellTypedAt (Γ : List Ty) (τ : Ty) (e : Expr) : Bool :=
  match getType e Γ with
  | some τ' => τ == τ'
  | none    => false
```

## Generator infrastructure available

You have the Palamedes `Gen α` monad with these primitives:

```lean
Gen.pick : Gen α → Gen α → Gen α         -- flip a coin between two generators
Gen.pure : α → Gen α                      -- deterministic, unconditional
Gen.bind : Gen α → (α → Gen β) → Gen β    -- sequence
-- plus standard do-notation
```

The `Gen` module is imported as `import Palamedes.Gen`. Supporting utilities are in `import Palamedes.Sample` (sampling) and `import Palamedes.Basic` (miscellaneous).

## Your task

Produce a Lean 4 source file defining:

```lean
def genWellTyped (Γ : List Ty) (τ : Ty) : Gen Expr
```

such that for every `Γ` and `τ`, every value `e` that `Gen.sample (genWellTyped Γ τ)` can return satisfies `wellTypedAt Γ τ e = true`.

## Hard constraints

1. The file must compile standalone in a Lake project that has `Palamedes` as a dependency and imports `CedarMicro.Ty` + `CedarMicro.Expr`. Include all necessary imports at the top.
2. The generator must be total (no `sorry`, no `partial`, no non-terminating recursion). Use a fuel parameter if needed.
3. The generator must be non-trivial: with a mixed context `Γ = [.int, .bool, .int]`, sampling 20 times should produce at least 3 distinct `bool` terms AND at least 3 distinct `int` terms, and at least one of them must use `var`, at least one must use `ite`, and at least one must use `and` (where applicable to that type).
4. Do not use `Classical.choice`, `native_decide`, or any unsafe primitive.
5. Return only the Lean source. No prose, no markdown, no code fences. Start with `import` and end with the last definition.

## Style guidance

- Prefer small, readable combinators over one monolithic definition.
- Factor out the per-type leaf-generation into a helper if it reduces duplication.
- Use `Gen.pick` to give the sampler real variety.

## What happens next

Your output will be written to a file called `CedarMicro/GenLLM.lean` in the kairos-cedar workbench and compiled inside a Docker image that has Lean 4.24.0, Mathlib, and Palamedes pre-installed. The compiled generator will be sampled 20 times at each of `τ = .bool` and `τ = .int` under `Γ = [.int, .bool, .int]`. Each sample will be runtime-evaluated against `wellTypedAt`. If the rejection rate exceeds 10%, you will be re-prompted with the rejected terms and their rejection reasons to refine the generator.
