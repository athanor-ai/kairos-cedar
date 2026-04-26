/-
  MeasureDiff.lean  - driver for the §8 diff-testing experiment.

  Usage:  lake env lean --run MeasureDiff.lean <n>

  Draws n samples from CedarFull.PolicyGen.genTuple (cycling through
  the finite support) and emits one tab-separated line per tuple:

    idx TAB principal TAB action TAB resource TAB policyText

  where:
    idx      - 0-based sample index
    principal  - EntityUID in "Type::eid" format (no quotes)
    action   - EntityUID in "Type::eid" format
    resource - EntityUID in "Type::eid" format
    policyText - Cedar policy text (spaces, no tabs)

  Python diff runner (experiments/phase_c_diff/run_diff.py) reads
  this output, invokes cedar authorize + cedar-go for each tuple,
  and emits the summary statistics.
-/
import CedarFull
import CedarFull.PolicyGen
import Cedar.Spec

open Cedar.Spec
open CedarFull
open CedarFull.PolicyGen

def main (args : List String) : IO Unit := do
  let n : Nat := (args.head?.getD "1000").toNat!
  let tuples := genTuple.val

  -- Cycle through the finite support to reach n samples.
  -- genTuple.val has a fixed finite number of elements (72 for the
  -- 3×3×3 request space × 8 policy shapes). We cycle to fill n.
  let supportSize := tuples.length
  if supportSize = 0 then
    IO.eprintln "ERROR: genTuple support is empty"
    return

  -- Build an array for O(1) indexing
  let arr := tuples.toArray

  for i in List.range n do
    let idx := i % supportSize
    if h : idx < arr.size then
      let (schema, req, pol) := arr[idx]
      let line := tupleToLine i schema req pol
      IO.println line
    else
      IO.eprintln s!"ERROR: index out of bounds at {i}"
