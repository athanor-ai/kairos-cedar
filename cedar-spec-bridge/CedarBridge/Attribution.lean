/-
  CedarBridge.Attribution. Mechanises the paper's
  spec-source-attribution function (paper §VIII.B) and proves its
  totality against cedar-spec's `Cedar.Spec.isAuthorized`.

  Paper §VIII.B argues totality informally: "totality is immediate
  from the hypothesis r != g". This file lifts that argument to a
  Lean theorem so the attribution claim no longer depends on
  trusting an English sentence.

  Theorem statement: for every (request, entities, policies) tuple
  and every two implementation decisions r and g such that r != g,
  cedar-spec's `isAuthorized.decision` equals one of r or g. The
  attribution function therefore yields a well-defined verdict in
  every disagreement case, mechanically.

  This is a finite-type pigeonhole: cedar-spec's `Decision` has
  exactly two inhabitants (`.allow`, `.deny`), so r != g forces
  {r, g} = {.allow, .deny} and any spec verdict falls in that set.
  The proof closes by `decide` on the two-element type.
-/
module

public import Cedar.Spec
public import Cedar.Spec.Authorizer
public import Cedar.Spec.Response

-- This file's proofs use simp args defensively (proving the goal under
-- multiple if-then-else simplification orderings). Lean 4.29.1's
-- unusedSimpArgs linter sometimes flags these as unused even when the
-- proof obligation requires them under a particular reduction order.
set_option linter.unusedSimpArgs false

namespace CedarBridge

open Cedar.Spec

/--
  Paper attribution function. Returns the implementation that the
  cedar-spec semantics agrees with, or `bothDiverge` if the spec
  disagrees with both.

  In paper text the function signature is
  `attributionDecision(r, g, p, q) -> {rust-correct, go-correct, both-diverge}`.
  Here `r` and `g` are the two implementation decisions and the
  remaining arguments wire cedar-spec's `isAuthorized` for the
  spec-source verdict.
-/
public inductive Attribution where
  | rustCorrect
  | goCorrect
  | bothDiverge
  deriving Repr, DecidableEq

/--
  Compute the attribution verdict for a given (request, entities,
  policies) triple and a pair of implementation decisions.
-/
public def attributionDecision
    (rDecision gDecision : Decision)
    (req : Request) (entities : Entities) (policies : Policies)
    : Attribution :=
  let specDecision := (Cedar.Spec.isAuthorized req entities policies).decision
  if specDecision = rDecision then .rustCorrect
  else if specDecision = gDecision then .goCorrect
  else .bothDiverge

/--
  Totality theorem. When the two implementations disagree, the
  cedar-spec authoriser fixes a verdict in {r, g}. Therefore the
  attribution function returns either `rustCorrect` or `goCorrect`,
  never `bothDiverge`.

  Formal statement: for all `r != g`, the spec decision belongs to
  the doubleton `{r, g}`. The proof is a case-split on `Decision`:
  it has two inhabitants, so r != g forces them to cover the type,
  and any value of `Decision` (in particular the spec decision) is
  one of r or g.

  This is the mechanisation of paper §VIII.B's informal statement
  "totality is immediate from the hypothesis r != g". The work the
  theorem does for the paper is to close the gap between
  spec-source-read attribution (a human reads cedar-spec source
  files and writes the verdict) and a runtime-mechanical witness:
  the spec decision is mechanically computed by `isAuthorized` and
  the attribution function is mechanically total when the two
  implementations disagree.
-/
public theorem attribution_total
    (rDecision gDecision : Decision)
    (h : rDecision ≠ gDecision)
    (req : Request) (entities : Entities) (policies : Policies) :
    let specDecision := (Cedar.Spec.isAuthorized req entities policies).decision
    specDecision = rDecision ∨ specDecision = gDecision := by
  cases rDecision <;> cases gDecision <;> simp_all <;>
    cases (Cedar.Spec.isAuthorized req entities policies).decision <;> simp

end CedarBridge
