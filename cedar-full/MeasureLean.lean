/-
  MeasureLean.lean - Lean oracle driver for the three-way diff experiment.

  Usage:  lake env lean --run MeasureLean.lean <n>
       or (after `lake build`): .lake/build/bin/measure-lean <n>

  Draws n samples from CedarFull.PolicyGen.genTuple (the same finite
  support used by measure-diff), evaluates each tuple through
  Cedar.Spec.isAuthorized using the fixed entity store defined in
  CedarFull.LeanOracle, and emits one JSON line per tuple:

    {"idx": "0", "decision": "Allow"}
    {"idx": "1", "decision": "Deny"}
    ...

  The lean_runner.py wrapper in experiments/phase_c_diff/ calls this
  binary and joins its output against measure-diff's TSV output (which
  carries the policy text and request fields) so run_diff.py can compare
  all three oracles on the same tuples.

  Design notes:
  - No Cedar text parsing is needed: we call isAuthorized directly on
    the Lean AST values produced by the generator, bypassing the
    cedar-policy / cedar-go text serialization round-trip.
  - The entity store (CedarFull.LeanOracle.fixedEntities) is built once
    at startup and shared across all tuples.
  - Decision derives Lean.ToJson so we use Lean.toJson for the output.
-/
import CedarFull
import CedarFull.PolicyGen
import CedarFull.LeanOracle
import Cedar.Spec

open Cedar.Spec
open CedarFull
open CedarFull.PolicyGen
open CedarFull.LeanOracle

def main (args : List String) : IO Unit := do
  let n : Nat := (args.head?.getD "1000").toNat!
  let tuples := genTuple.val

  let supportSize := tuples.length
  if supportSize = 0 then
    IO.eprintln "ERROR: genTuple support is empty"
    return

  let arr := tuples.toArray

  for i in List.range n do
    let idx := i % supportSize
    if h : idx < arr.size then
      let (_, req, pol) := arr[idx]
      let dec := decisionStr req pol
      -- Emit a compact JSON object; idx is the global sample counter i
      -- (matching MeasureDiff.lean's convention) so the Python runner
      -- can join on idx without ambiguity.
      IO.println s!"\{\"idx\": \"{i}\", \"decision\": \"{dec}\"}"
    else
      IO.eprintln s!"ERROR: index out of bounds at {i}"
