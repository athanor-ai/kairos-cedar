/-
  Measurement driver: emit all N samples with constructor + depth per line,
  for the paper §5.3 Table 1 histograms.

  Usage (inside the monolith container):
    lake env lean --run MeasureAll.lean 10000

  Output format: one line per sample, tab-separated:
    ctype<TAB>depth<TAB>expr
  where ctype ∈ {bool, int}, depth is the AST depth, and expr is the
  exprToString pretty form.
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
  let n : Nat := (args.head?.getD "10000").toNat!
  let Γ : List CedarMicro.Ty := [.int, .bool, .int]

  let boolSamples ← sampleN n (CedarMicro.genWellTyped Γ .bool)
  let intSamples  ← sampleN n (CedarMicro.genWellTyped Γ .int)

  for e in boolSamples do
    IO.println s!"bool\t{exprRootCtor e}\t{exprDepth e}\t{exprShort e}"
  for e in intSamples do
    IO.println s!"int\t{exprRootCtor e}\t{exprDepth e}\t{exprShort e}"
