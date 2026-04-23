/- Sample + verify driver for the LLM-synthesised generator in
   CedarMicro.GenLLM. Exists in parallel to Main.lean, which drives
   the hand-authored generator from CedarMicro.WellTyped. -/

import CedarMicro
import Palamedes.Basic
import Palamedes.Sample

-- The LLM-synthesised generator lives at the root namespace.
-- Bring our hand-authored typechecker into scope for verification.
open CedarMicro

def exprStr : CedarMicro.Expr → String
  | .litInt n  => s!"{n}"
  | .litBool b => if b then "true" else "false"
  | .var n     => s!"v{n}"
  | .ite c t f => s!"(if {exprStr c} then {exprStr t} else {exprStr f})"
  | .and a b   => s!"({exprStr a} && {exprStr b})"

def tyStr : CedarMicro.Ty → String
  | .bool => "bool"
  | .int  => "int"

def main (args : List String) : IO Unit := do
  let n := (args.head?.getD "20").toNat!
  let Γ : List CedarMicro.Ty := [.int, .bool, .int]
  IO.println s!"Sampling {n} expressions from LLM-SYNTHESISED genWellTyped"
  IO.println s!"   context Γ = [{String.intercalate ", " (Γ.map tyStr)}]"
  IO.println ""

  let boolSamples ← sampleN n (_root_.genWellTyped Γ .bool)
  let intSamples  ← sampleN n (_root_.genWellTyped Γ .int)

  let boolOk := boolSamples.all (wellTypedAt Γ .bool)
  let intOk  := intSamples.all (wellTypedAt Γ .int)
  let boolVerified := boolSamples.countP (wellTypedAt Γ .bool)
  let intVerified  := intSamples.countP (wellTypedAt Γ .int)

  let boolTag := if boolOk then "PASS" else "FAIL"
  let intTag := if intOk then "PASS" else "FAIL"
  IO.println s!"   bool: {boolVerified}/{n} verified well-typed {boolTag}"
  IO.println s!"   int:  {intVerified}/{n}  verified well-typed {intTag}"
  IO.println ""

  IO.println "First 8 bool samples:"
  for e in boolSamples.take 8 do
    let tag := if wellTypedAt Γ .bool e then "OK" else "REJECT"
    IO.println s!"  [{tag}] {exprStr e}"

  IO.println ""
  IO.println "First 8 int samples:"
  for e in intSamples.take 8 do
    let tag := if wellTypedAt Γ .int e then "OK" else "REJECT"
    IO.println s!"  [{tag}] {exprStr e}"

  IO.println ""
  let total := 2 * n
  let verified := boolVerified + intVerified
  let rejection := 100.0 * (total - verified).toFloat / total.toFloat
  IO.println s!"Result: {verified}/{total} LLM-synthesised samples pass Lean predicate."
  IO.println s!"   rejection rate: {rejection}%"
