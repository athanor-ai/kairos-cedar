/-
  Measurement driver for the hand-authored full-Cedar generator.

  Usage:  lake env lean --run MeasureFull.lean <n>

  For each target τ ∈ {bool(.anyBool), int, string}, draws n
  samples from CedarFull.genWellTyped (default : TypeEnv) τ and
  emits:
    <target>\t<root-ctor>\t<wellTypedAt>\t<term>

  where <root-ctor> names the top-level Cedar.Spec.Expr constructor
  and <wellTypedAt> is Bool (runtime-verified type-correctness under
  the default TypeEnv).

  Matches the CedarMicro MeasureAll.lean pattern but over the
  full 12-constructor Cedar.Spec.Expr.
-/
import CedarFull
import Cedar.Spec
import Cedar.Validation

open Cedar.Spec
open Cedar.Validation
open CedarFull

def exprRootCtor : Expr → String
  | .lit _       => "lit"
  | .var _       => "var"
  | .ite _ _ _   => "ite"
  | .and _ _     => "and"
  | .or _ _      => "or"
  | .unaryApp _ _ => "unaryApp"
  | .binaryApp _ _ _ => "binaryApp"
  | .getAttr _ _ => "getAttr"
  | .hasAttr _ _ => "hasAttr"
  | .set _       => "set"
  | .record _    => "record"
  | .call _ _    => "call"

def exprShort (e : Expr) : String :=
  -- Use reprStr for machine-readable round-trip of the term.
  (reprStr e).replace "\n" " "

def main (args : List String) : IO Unit := do
  let n : Nat := (args.head?.getD "10000").toNat!
  let env : TypeEnv := default
  let targets : List (String × CedarType) :=
    [ ("bool",   .bool .anyBool)
    , ("int",    .int)
    , ("string", .string)
    ]

  for (tag, τ) in targets do
    let gen := CedarFull.genWellTyped env τ
    -- gen : CedarFull.Gen Expr; gen.val : List Expr. Take first n.
    let samples := gen.val.take n
    for e in samples do
      let wt := CedarFull.wellTypedAt env e
      IO.println s!"{tag}\t{exprRootCtor e}\t{wt}\t{exprShort e}"
