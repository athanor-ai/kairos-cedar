/-
  MeasureRego: CLI driver that emits the Lean spec's decisions for all
  (shape, input) pairs as tab-separated lines.

  Output format (one line per tuple):
    shape_name TAB input_name TAB spec_result TAB policy_rego TAB input_json

  where spec_result ∈ {"true", "false", "undefined"}.

  The Python diff runner (`experiments/phase_k_opa_diff/run_opa_diff.py`) reads
  this output, runs each policy through OPA, and reports disagreements.
-/

import RegoFull.PolicyGen

open RegoFull.PolicyGen

def main : IO Unit := do
  for shape in allShapes do
    for (inputName, inp) in sampleInputs do
      IO.println (tupleToLine shape inputName inp)
