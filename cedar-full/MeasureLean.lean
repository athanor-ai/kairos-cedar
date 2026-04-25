/-
  MeasureLean.lean — Lean evaluator oracle for the §8 diff-testing experiment.

  Usage:  echo -e "0\n1\n2\n..." | lake env lean --run MeasureLean.lean

  Reads tab-separated tuples from stdin, one per line. Each line is

    idx \t principal \t action \t resource \t policyText

  identical to the format MeasureDiff.lean emits. The first column (idx) is
  the canonical key — Lean re-derives the (Schema, Request, Policy) triple
  from `genTuple.val[idx % supportSize]`, which is the SAME generator the
  Rust + Go runners are evaluating against (cedar-spec ships no Lean parser,
  and the Lean-side AST is the source of truth that gets serialized to text).

  For each line, evaluates `Cedar.Spec.isAuthorized request entities policies`
  on a fixed entity store matching `experiments/phase_c_diff/run_diff.py`'s
  FIXED_ENTITIES (empty attrs, no parents — so `principal in Group::"admins"`
  is false, `context has "approved"` is false, etc.). Emits

    idx \t Allow|Deny

  to stdout. Parse failures emit `idx \t ERROR:reason` so downstream
  three-way diff logic can handle them uniformly.

  Why idx-keyed (not text-parse): cedar-spec exposes an evaluator over
  `Cedar.Spec.Policy` (an AST), but no Lean text parser exists upstream.
  The Lean-generated text round-trips through Rust/Go which DO have parsers,
  so the serialization↔parse loop is a Cedar-side concern. The Lean oracle
  evaluates the canonical AST directly, sidestepping that loop entirely.
-/
import CedarFull
import CedarFull.PolicyGen
import Cedar.Spec

open Cedar.Spec
open Cedar.Data
open CedarFull
open CedarFull.PolicyGen

/-- Build the fixed entity store matching FIXED_ENTITIES in run_diff.py.
    All entities have empty attrs and no parents — keep this in lockstep
    with the Python Go/Rust runners' entity files. -/
def fixedEntities : Entities :=
  let users   := [
    (mkUID "User" "alice",
     ({ attrs := Map.empty, ancestors := Set.empty, tags := Map.empty } : EntityData)),
    (mkUID "User" "bob",
     ({ attrs := Map.empty, ancestors := Set.empty, tags := Map.empty } : EntityData)),
    (mkUID "User" "carol",
     ({ attrs := Map.empty, ancestors := Set.empty, tags := Map.empty } : EntityData))
  ]
  let docs := [
    (mkUID "Document" "doc1",
     ({ attrs := Map.empty, ancestors := Set.empty, tags := Map.empty } : EntityData)),
    (mkUID "Document" "doc2",
     ({ attrs := Map.empty, ancestors := Set.empty, tags := Map.empty } : EntityData))
  ]
  let photos := [
    (mkUID "Photo" "photo1",
     ({ attrs := Map.empty, ancestors := Set.empty, tags := Map.empty } : EntityData))
  ]
  let actions := [
    (mkUID "Action" "view",
     ({ attrs := Map.empty, ancestors := Set.empty, tags := Map.empty } : EntityData)),
    (mkUID "Action" "edit",
     ({ attrs := Map.empty, ancestors := Set.empty, tags := Map.empty } : EntityData)),
    (mkUID "Action" "admin",
     ({ attrs := Map.empty, ancestors := Set.empty, tags := Map.empty } : EntityData))
  ]
  Map.make (users ++ docs ++ photos ++ actions)

/-- Emit `idx \t Allow|Deny` for one canonical (request, policy) pair. -/
def evaluateOne (idx : Nat) (req : Request) (pol : Policy) : String :=
  let resp := isAuthorized req fixedEntities [pol]
  let verdict := match resp.decision with
    | .allow => "Allow"
    | .deny  => "Deny"
  s!"{idx}\t{verdict}"

def main (_ : List String) : IO Unit := do
  let tuples := genTuple.val
  let supportSize := tuples.length
  if supportSize = 0 then
    IO.eprintln "ERROR: genTuple support is empty"
    return
  let arr := tuples.toArray

  -- Read all of stdin, line-by-line. Tolerate blank lines.
  let stdin ← IO.getStdin
  let mut buf : String := ""
  while true do
    let chunk ← stdin.read 65536
    if chunk.isEmpty then break
    buf := buf ++ String.fromUTF8! chunk

  for line in buf.splitOn "\n" do
    let line := line.trimAscii.toString
    if line.isEmpty then continue

    -- Pull the leading idx field. Format: "idx\tprincipal\taction\tresource\tpolicy".
    let parts := line.splitOn "\t"
    match parts with
    | [] => continue
    | idxStr :: _ =>
      match idxStr.toNat? with
      | none =>
        IO.println s!"{idxStr}\tERROR:bad-idx"
      | some i =>
        let modIdx := i % supportSize
        if h : modIdx < arr.size then
          let (_, req, pol) := arr[modIdx]
          IO.println (evaluateOne i req pol)
        else
          IO.println s!"{i}\tERROR:idx-oob"
