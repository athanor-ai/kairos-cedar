/-
  Cedar-micro generator driver.

  Samples N well-typed expressions from `CedarMicro.genWellTyped`,
  verifies each via `CedarMicro.wellTypedAt`, and prints sample output.

  Usage: `lake env cedar-micro-sample 10` (runs 10 samples per type)
-/

import CedarMicro
import Palamedes.Basic
import Palamedes.Sample

open CedarMicro

def exprToString : CedarMicro.Expr → String
  | .litInt n  => s!"{n}"
  | .litBool b => if b then "true" else "false"
  | .var n     => s!"v{n}"
  | .ite c t f => s!"(if {exprToString c} then {exprToString t} else {exprToString f})"
  | .and a b   => s!"({exprToString a} && {exprToString b})"

def tyToString : CedarMicro.Ty → String
  | .bool => "bool"
  | .int  => "int"

def main (args : List String) : IO Unit := do
  let n : Nat := (args.head?.getD "20").toNat!
  let Γ : List CedarMicro.Ty := [.int, .bool, .int]

  IO.println s!"Sampling {n} well-typed Cedar-micro expressions"
  let ctx := String.intercalate ", " (Γ.map tyToString)
  IO.println s!"   context Γ = [{ctx}]"
  IO.println ""

  let boolSamples ← sampleN n (genWellTyped Γ .bool)
  let intSamples  ← sampleN n (genWellTyped Γ .int)

  let boolOk := boolSamples.all (wellTypedAt Γ .bool)
  let intOk  := intSamples.all (wellTypedAt Γ .int)

  let boolTag := if boolOk then "PASS" else "FAIL"
  let intTag  := if intOk  then "PASS" else "FAIL"
  IO.println s!"   bool samples well-typed: {boolSamples.length}/{n} {boolTag}"
  IO.println s!"   int  samples well-typed: {intSamples.length}/{n} {intTag}"
  IO.println ""

  IO.println "First 5 bool samples:"
  for e in boolSamples.take 5 do
    IO.println s!"    {exprToString e}"
  IO.println ""

  IO.println "First 5 int samples:"
  for e in intSamples.take 5 do
    IO.println s!"    {exprToString e}"
  IO.println ""

  let total := boolSamples.length + intSamples.length
  if boolOk && intOk then
    IO.println s!"Result: all {total}/{total} generated expressions satisfy isWellTyped Γ."
  else
    IO.println "Result: FAILURE. Some sampled expressions do not type-check."
