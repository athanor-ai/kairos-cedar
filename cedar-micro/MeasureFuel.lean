/-
  Fuel sweep for the hand-authored CedarMicro generator.

  Usage:  lake env lean --run MeasureFuel.lean <fuel> <n>

  For each of τ ∈ {bool, int}, draws n samples from
  genSize Γ fuel τ under the canonical Γ = [int, bool, int].
  Emits one tsv line per sample:
    <target>\t<root-ctor>\t<depth>\t<expr>
-/
import CedarMicro
import Palamedes.Basic
import Palamedes.Sample

open CedarMicro

def exprShort : CedarMicro.Expr → String
  | .litInt n  => s!"{n}"
  | .litBool b => if b then "true" else "false"
  | .var n     => s!"v{n}"
  | .ite c t f => s!"(if {exprShort c} then {exprShort t} else {exprShort f})"
  | .and a b   => s!"({exprShort a} && {exprShort b})"

def exprDepth : CedarMicro.Expr → Nat
  | .litInt _ | .litBool _ | .var _ => 0
  | .ite c t f => 1 + max (exprDepth c) (max (exprDepth t) (exprDepth f))
  | .and a b   => 1 + max (exprDepth a) (exprDepth b)

def exprRootCtor : CedarMicro.Expr → String
  | .litInt _  => "litInt"
  | .litBool _ => "litBool"
  | .var _     => "var"
  | .ite _ _ _ => "ite"
  | .and _ _   => "and"

def main (args : List String) : IO Unit := do
  let fuel : Nat := (args.head?.getD "2").toNat!
  let n : Nat := (args.get? 1 |>.getD "10000").toNat!
  let Γ : List CedarMicro.Ty := [.int, .bool, .int]

  let boolSamples ← sampleN n (CedarMicro.genSize Γ fuel .bool)
  let intSamples  ← sampleN n (CedarMicro.genSize Γ fuel .int)

  for e in boolSamples do
    IO.println s!"bool\t{exprRootCtor e}\t{exprDepth e}\t{exprShort e}"
  for e in intSamples do
    IO.println s!"int\t{exprRootCtor e}\t{exprDepth e}\t{exprShort e}"
