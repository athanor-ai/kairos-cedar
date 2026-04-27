/-
  CedarFull.LeanOracle: fixed entity store for use by MeasureLean.lean.

  Mirrors the FIXED_ENTITIES constant in experiments/phase_c_diff/run_diff.py
  so the Lean oracle evaluates requests against the same entity graph that
  cedar-policy (Rust) and cedar-go (Go) see.

  Entity graph:
    User::"alice"   attrs: { address: { city: "Seattle", street: "Main", zip: "98101" } }
    User::"bob"     attrs: { address: { city: "Seattle", street: "Main", zip: "98101" } }
    User::"carol"   attrs: { address: { city: "Seattle", street: "Main", zip: "98101" } }
    Document::"doc1"  attrs: { owner: User::"alice" }
    Document::"doc2"  attrs: { owner: User::"alice" }
    Photo::"photo1"   attrs: {}
    Action::"view"    attrs: {}
    Action::"edit"    attrs: {}
    Action::"admin"   attrs: {}

  All entities have empty ancestor sets and empty tag maps (the generator
  policies do not exercise hierarchy or tags so far).
-/

import CedarFull.PolicyGen

open Cedar.Spec
open Cedar.Data
open CedarFull.PolicyGen

namespace CedarFull.LeanOracle

-- ── address record value ─────────────────────────────────────────────
private def defaultAddress : Value :=
  .record (Map.make
    [ ("city",   .prim (.string "Seattle"))
    , ("street", .prim (.string "Main"))
    , ("zip",    .prim (.string "98101"))
    ])

-- ── entity builder helpers ───────────────────────────────────────────
private def mkEntityData (attrs : Map Attr Value) : EntityData :=
  { attrs      := attrs
  , ancestors  := Set.empty
  , tags       := Map.empty
  }

-- ── fixed entity store ───────────────────────────────────────────────
/-- The fixed entity store matching FIXED_ENTITIES in run_diff.py. -/
def fixedEntities : Entities :=
  Map.make
    [ -- User principals
      (mkUID "User" "alice",
        mkEntityData (Map.make [("address", defaultAddress)]))
    , (mkUID "User" "bob",
        mkEntityData (Map.make [("address", defaultAddress)]))
    , (mkUID "User" "carol",
        mkEntityData (Map.make [("address", defaultAddress)]))
    -- Document resources
    , (mkUID "Document" "doc1",
        mkEntityData (Map.make [("owner", .prim (.entityUID (mkUID "User" "alice")))]))
    , (mkUID "Document" "doc2",
        mkEntityData (Map.make [("owner", .prim (.entityUID (mkUID "User" "alice")))]))
    -- Photo resource
    , (mkUID "Photo" "photo1",
        mkEntityData Map.empty)
    -- Action entities (cedar-go may look them up)
    , (mkUID "Action" "view",  mkEntityData Map.empty)
    , (mkUID "Action" "edit",  mkEntityData Map.empty)
    , (mkUID "Action" "admin", mkEntityData Map.empty)
    ]

/-- Evaluate one (request, policy) pair under fixedEntities and return the
    Decision as a string: "Allow" or "Deny". -/
def decisionStr (req : Request) (pol : Policy) : String :=
  let resp := Cedar.Spec.isAuthorized req fixedEntities [pol]
  match resp.decision with
  | .allow => "Allow"
  | .deny  => "Deny"

end CedarFull.LeanOracle
