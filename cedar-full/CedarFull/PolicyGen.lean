/-
  CedarFull.PolicyGen: a minimal, static-schema Policy+Schema+Request generator.

  Paper §8 setup: each run draws N tuples from the generator. This module
  provides `genTuple : Gen (Cedar.Spec.Schema × Cedar.Spec.Request × Cedar.Spec.Policy)`
  using a fixed schema (User, Group, Document, Photo; view, edit, admin).

  Design rationale for N=10000 pass:
    • Schema is fixed (a single hardcoded Schema value); schema diversity is future work.
    • Request varies over 9 (principal × action × resource) combinations.
    • Policy varies over 25 shapes covering:
        – bare permit/forbid (any scope),
        – principal/resource/action equality in scope,
        – principal/resource is-type in scope,
        – principal/resource in-group in scope,
        – when/unless condition blocks using equality, in, is, has, getAttr on
          principal, action, resource, and context.
      Total support size: 9 × 25 = 225 distinct (request, policy) pairs.
      At N=10000 we sample with replacement across this 225-element pool.

  All generators produce values in the Gen monad (List-backed, defined in
  CedarFull.Expr). No sorry, no admit, no native_decide.

  Cedar text serializers (policyToText / requestToText) are provided so the
  MeasureDiff.lean driver can emit JSON-per-tuple for the Python diff runner.
-/

import CedarFull.Expr
import CedarBridge

open Cedar.Spec
open Cedar.Validation
open Cedar.Data
open CedarFull

namespace CedarFull.PolicyGen

-- ── Entity type helpers ──────────────────────────────────────────────

/-- Build a simple Cedar EntityType from a name string (no namespace). -/
def mkEty (name : String) : EntityType := { id := name, path := [] }

/-- Build a Cedar EntityUID from type name + id string. -/
def mkUID (tyName : String) (eid : String) : EntityUID :=
  { ty := mkEty tyName, eid := eid }

-- ── Fixed schema definition ──────────────────────────────────────────
--
-- Schema:
--   entity User;
--   entity Group;
--   entity Document;
--   entity Photo;
--
--   action view appliesTo { principal: User, resource: [Document, Photo] };
--   action edit appliesTo { principal: User, resource: [Document, Photo] };
--   action admin appliesTo { principal: User, resource: [Document, Photo] };

/-- Address record type used as User.address attribute (V2 §8 widening). -/
def addressRecordType : RecordType :=
  Map.make
    [ ("city",   .required .string)
    , ("street", .required .string)
    , ("zip",    .required .string)
    ]

/-- The fixed entity schema (V2 §8 widening):
      User has `address: { city: String, street: String, zip: String }`,
      Document has `owner: User`,
      Group/Photo are attribute-free.
    The attributes give the new nested-attr / has / record-literal shapes
    a non-trivial schema target.  cedar-drt §8 reports differential bugs
    on schemas with attribute records; widening enables those tests. -/
def fixedEntitySchema : EntitySchema :=
  Map.make
    [ (mkEty "User",
        EntitySchemaEntry.standard
          { ancestors := Set.empty
          , attrs     := Map.make [("address", .required (.record addressRecordType))]
          , tags      := none })
    , (mkEty "Group",
        EntitySchemaEntry.standard
          { ancestors := Set.empty, attrs := Map.empty, tags := none })
    , (mkEty "Document",
        EntitySchemaEntry.standard
          { ancestors := Set.empty
          , attrs     := Map.make [("owner", .required (.entity (mkEty "User")))]
          , tags      := none })
    , (mkEty "Photo",
        EntitySchemaEntry.standard
          { ancestors := Set.empty, attrs := Map.empty, tags := none })
    ]

/-- The fixed action schema: view, edit, admin  - each applies to User × {Document, Photo}. -/
def fixedActionEntry : ActionSchemaEntry :=
  { appliesToPrincipal := Set.make [mkEty "User"]
  , appliesToResource  := Set.make [mkEty "Document", mkEty "Photo"]
  , ancestors          := Set.empty
  , context            := Map.empty
  }

def fixedActionSchema : ActionSchema :=
  Map.make
    [ (mkUID "Action" "view",  fixedActionEntry)
    , (mkUID "Action" "edit",  fixedActionEntry)
    , (mkUID "Action" "admin", fixedActionEntry)
    ]

/-- The fixed Schema value used across all generated tuples. -/
def fixedSchema : Schema :=
  { ets := fixedEntitySchema, acts := fixedActionSchema }

-- ── genSchema ───────────────────────────────────────────────────────

/-- Schema generator: returns the single fixed schema.
    Future work: vary attribute structure, hierarchy depth, action granularity. -/
def genSchema : Gen Schema := pure fixedSchema

-- ── genRequest ──────────────────────────────────────────────────────
--
-- Principals: User::"alice", User::"bob", User::"carol"
-- Actions:    Action::"view", Action::"edit", Action::"admin"
-- Resources:  Document::"doc1", Photo::"photo1", Document::"doc2"
-- Context:    empty
--
-- We enumerate all 3 × 3 × 3 = 27 combinations (actually 3×3×3 below
-- picks 3 principals × 3 actions × 3 resources = 27, deduped by Gen.pick).

def principals : List EntityUID :=
  [ mkUID "User" "alice", mkUID "User" "bob", mkUID "User" "carol" ]

def actions : List EntityUID :=
  [ mkUID "Action" "view", mkUID "Action" "edit", mkUID "Action" "admin" ]

def resources : List EntityUID :=
  [ mkUID "Document" "doc1", mkUID "Photo" "photo1", mkUID "Document" "doc2" ]

/-- Lift a list of values into a Gen that returns any one of them. -/
def genAny {α : Type} (xs : List α) : Gen α := ⟨xs⟩

-- ── Random scope generators (Stage 5: drop hardcoded scopes) ────────
--
-- Mike's load-bearing critique: PolicyGen had 41 hardcoded policy
-- shapes pinning specific entity UIDs, attribute names, and scope
-- forms. The generators below replace that with a true random-policy
-- generator: each scope is drawn from the 5 Cedar Scope variants
-- (.any / .eq / .mem / .is / .isMem) over the schema's declared
-- entity types and UIDs. ActionScope additionally has the
-- `actionInAny` variant.
--
-- Schema-conditioning: every scope produced is valid against
-- fixedSchema. principalUIDs / resourceUIDs / actionUIDs are the
-- declared instances; principalTypes / resourceTypes / actionTypes
-- are the declared entity types. typecheckPolicy on the scope
-- toExpr (.binaryApp .eq, .mem, .unaryApp .is) requires the
-- entity-type to be in env.ets — which it is by construction.

def principalTypes : List EntityType :=
  [ mkEty "User" ]

def resourceTypes : List EntityType :=
  [ mkEty "Document", mkEty "Photo" ]

def actionTypes : List EntityType :=
  [ mkEty "Action" ]

/-- Generate a Cedar Scope across all 5 variants. The .any / .is /
    .isMem cases use entity types; .eq / .mem / .isMem use entity UIDs.
    This is a generic scope-builder; principal / resource / action
    wrap it via genPrincipalScope / genResourceScope / genActionScope. -/
def genScope (uids : List EntityUID) (etys : List EntityType) : Gen Scope :=
  Gen.pick (pure .any)
  (Gen.pick
    (do let uid ← genAny uids; pure (.eq uid))
  (Gen.pick
    (do let uid ← genAny uids; pure (.mem uid))
  (Gen.pick
    (do let ety ← genAny etys; pure (.is ety))
    (do let ety ← genAny etys
        let uid ← genAny uids
        pure (.isMem ety uid)))))

def genPrincipalScope : Gen PrincipalScope :=
  do let s ← genScope principals principalTypes
     pure (.principalScope s)

def genResourceScope : Gen ResourceScope :=
  do let s ← genScope resources resourceTypes
     pure (.resourceScope s)

/-- ActionScope has 5 scope-style variants plus the actionInAny variant
    (a list of EntityUIDs, semantically a set-membership). The
    spec-level note in cedar-spec/Cedar/Spec/Policy.lean:46 explicitly
    permits `is` constraints on actions in the abstract grammar even
    though the concrete grammar disallows them. -/
def genActionScope : Gen ActionScope :=
  Gen.pick
    (do let s ← genScope actions actionTypes
        pure (.actionScope s))
    (pure (.actionInAny actions))

/-- Effects: permit / forbid. -/
def effects : List Effect := [.permit, .forbid]

-- ── genRequest ──────────────────────────────────────────────────────

/-- Generate a request conditioned on `fixedSchema`.
    Picks from 27 (principal, action, resource) triples; context is always empty. -/
def genRequest (_ : Schema) : Gen Request :=
  do let p ← genAny principals
     let a ← genAny actions
     let r ← genAny resources
     pure { principal := p, action := a, resource := r, context := Map.empty }

-- ── genPolicy ───────────────────────────────────────────────────────
--
-- 25 policy shapes (8 scope-only originals + 17 new: is/in-group/actionInAny scopes + when/unless conditions).
-- Shape 25 uses genWellTyped for an arbitrary well-typed condition.

/-- The default TypeEnv derived from fixedSchema for use with genWellTyped.
    RequestType: principal=User, action=Action::"view", resource=Document, context=∅ -/
def fixedEnv : TypeEnv :=
  { ets  := fixedEntitySchema
  , acts := fixedActionSchema
  , reqty :=
    { principal := mkEty "User"
    , action    := mkUID "Action" "view"
    , resource  := mkEty "Document"
    , context   := Map.empty
    }
  }

-- ── Random conditions + random policy (depends on fixedEnv) ─────────

/-- Random condition list: empty, single-when, or single-unless.
    when/unless bodies are drawn from genWellTyped at .bool .anyBool
    (typing-correct by genSize_sound). -/
def genRandomConditions : Gen Conditions :=
  Gen.pick (pure [])
  (Gen.pick
    (do let body ← genWellTyped fixedEnv (.bool .anyBool)
        pure [{ kind := .when, body := body }])
    (do let body ← genWellTyped fixedEnv (.bool .anyBool)
        pure [{ kind := .unless, body := body }]))

/-- Main random-policy generator. Combines random effect (permit/forbid),
    random principal/action/resource scope (5+ variants each), and a
    random condition list (empty / when{} / unless{}). The Mike-Hicks
    "load-bearing" change: this replaces the bulk of the previously
    hardcoded scope-only and condition-only templates with a single
    truly randomized generator. -/
def genRandomPolicy : Gen Policy :=
  do let eff ← genAny effects
     let p   ← genPrincipalScope
     let a   ← genActionScope
     let r   ← genResourceScope
     let cs  ← genRandomConditions
     pure
       { id             := "random"
       , effect         := eff
       , principalScope := p
       , actionScope    := a
       , resourceScope  := r
       , condition      := cs
       }

-- ── Policy shape helpers ─────────────────────────────────────────────

private def permitAny : Policy :=
  { id             := "permit-any"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := []
  }

private def forbidAny : Policy :=
  { id             := "forbid-any"
  , effect         := .forbid
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := []
  }

private def permitIfPrincipalEqAlice : Policy :=
  { id             := "permit-principal-eq-alice"
  , effect         := .permit
  , principalScope := .principalScope (.eq (mkUID "User" "alice"))
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := []
  }

private def permitIfPrincipalEqBob : Policy :=
  { id             := "permit-principal-eq-bob"
  , effect         := .permit
  , principalScope := .principalScope (.eq (mkUID "User" "bob"))
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := []
  }

private def forbidIfResourceEqDoc1 : Policy :=
  { id             := "forbid-resource-eq-doc1"
  , effect         := .forbid
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope (.eq (mkUID "Document" "doc1"))
  , condition      := []
  }

private def permitForActionView : Policy :=
  { id             := "permit-action-view"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope (.eq (mkUID "Action" "view"))
  , resourceScope  := .resourceScope .any
  , condition      := []
  }

private def forbidForActionAdmin : Policy :=
  { id             := "forbid-action-admin"
  , effect         := .forbid
  , principalScope := .principalScope .any
  , actionScope    := .actionScope (.eq (mkUID "Action" "admin"))
  , resourceScope  := .resourceScope .any
  , condition      := []
  }

/-- Build a policy with a `when {<condExpr>}` clause from a generated bool Expr. -/
def policyWithWhenCond (condExpr : Expr) : Policy :=
  { id             := "permit-with-when-cond"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when, body := condExpr }]
  }

/-- Same scope/effect as `policyWithWhenCond` but the condition is wrapped
    in `unless` instead of `when`. Together with the three siblings below
    they form the four-way effect × condition-kind crosscut that runs the
    randomly-generated condExpr through every policy-evaluator branch. -/
def policyWithUnlessCond (condExpr : Expr) : Policy :=
  { id             := "permit-with-unless-cond"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .unless, body := condExpr }]
  }

def forbidPolicyWithWhenCond (condExpr : Expr) : Policy :=
  { id             := "forbid-with-when-cond"
  , effect         := .forbid
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when, body := condExpr }]
  }

def forbidPolicyWithUnlessCond (condExpr : Expr) : Policy :=
  { id             := "forbid-with-unless-cond"
  , effect         := .forbid
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .unless, body := condExpr }]
  }

/-- Restricted-scope random-condition variant. The scope (principal is
    User) is the most common Cedar scope shape in production rules, so a
    randomly-conditioned policy under that scope exercises the
    scope-then-condition evaluator path that the `.any` shapes do not. -/
def policyWithIsUserAndWhenCond (condExpr : Expr) : Policy :=
  { id             := "permit-principal-is-user-with-when-cond"
  , effect         := .permit
  , principalScope := .principalScope (.is (mkEty "User"))
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when, body := condExpr }]
  }

-- ── New shapes 9–25 ───────────────────────────────────────────────────────────────────

-- Shape 9: principal is User (is-type in scope)
private def permitPrincipalIsUser : Policy :=
  { id             := "permit-principal-is-user"
  , effect         := .permit
  , principalScope := .principalScope (.is (mkEty "User"))
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := []
  }

-- Shape 10: resource is Document (is-type in scope)
private def permitResourceIsDocument : Policy :=
  { id             := "permit-resource-is-document"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope (.is (mkEty "Document"))
  , condition      := []
  }

-- Shape 11: resource is Photo (is-type in scope)
private def forbidResourceIsPhoto : Policy :=
  { id             := "forbid-resource-is-photo"
  , effect         := .forbid
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope (.is (mkEty "Photo"))
  , condition      := []
  }

-- Shape 12: principal in Group::"admins" (in-group scope)
private def permitPrincipalInAdmins : Policy :=
  { id             := "permit-principal-in-admins"
  , effect         := .permit
  , principalScope := .principalScope (.mem (mkUID "Group" "admins"))
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := []
  }

-- Shape 13: principal in Group::"viewers" (in-group scope)
private def forbidPrincipalInViewers : Policy :=
  { id             := "forbid-principal-in-viewers"
  , effect         := .forbid
  , principalScope := .principalScope (.mem (mkUID "Group" "viewers"))
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := []
  }

-- Shape 14: resource in Document::"folder1" (in scope for resource)
private def permitResourceInFolder : Policy :=
  { id             := "permit-resource-in-folder"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope (.mem (mkUID "Document" "folder1"))
  , condition      := []
  }

-- Shape 15: action in [view, edit] (actionInAny scope)
private def permitActionInViewEdit : Policy :=
  { id             := "permit-action-in-view-edit"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionInAny [mkUID "Action" "view", mkUID "Action" "edit"]
  , resourceScope  := .resourceScope .any
  , condition      := []
  }

-- Shape 16: when { principal == User::"alice" } (equality on principal in condition)
private def permitWhenPrincipalEqAlice : Policy :=
  { id             := "permit-when-principal-eq-alice"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .binaryApp .eq (.var .principal) (.lit (.entityUID (mkUID "User" "alice"))) }]
  }

-- Shape 17: when { action == Action::"view" } (equality on action in condition)
private def permitWhenActionEqView : Policy :=
  { id             := "permit-when-action-eq-view"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .binaryApp .eq (.var .action) (.lit (.entityUID (mkUID "Action" "view"))) }]
  }

-- Shape 18: when { resource == Document::"doc1" } (equality on resource in condition)
private def forbidWhenResourceEqDoc1 : Policy :=
  { id             := "forbid-when-resource-eq-doc1"
  , effect         := .forbid
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .binaryApp .eq (.var .resource) (.lit (.entityUID (mkUID "Document" "doc1"))) }]
  }

-- Shape 19: when { principal in Group::"admins" } (in operator on principal in condition)
private def permitWhenPrincipalInAdmins : Policy :=
  { id             := "permit-when-principal-in-admins"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .binaryApp .mem (.var .principal) (.lit (.entityUID (mkUID "Group" "admins"))) }]
  }

-- Shape 20: when { resource is Document } (is type-guard on resource in condition)
private def permitWhenResourceIsDocument : Policy :=
  { id             := "permit-when-resource-is-document"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .unaryApp (.is (mkEty "Document")) (.var .resource) }]
  }

-- Shape 21: when { principal is User } (is type-guard on principal in condition)
private def permitWhenPrincipalIsUser : Policy :=
  { id             := "permit-when-principal-is-user"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .unaryApp (.is (mkEty "User")) (.var .principal) }]
  }

-- Shape 22: when { context has "approved" } (has operator on context)
private def permitWhenContextHasApproved : Policy :=
  { id             := "permit-when-context-has-approved"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .hasAttr (.var .context) "approved" }]
  }

-- Shape 23: unless { resource == Document::"doc2" } (unless + equality)
private def forbidUnlessResourceEqDoc2 : Policy :=
  { id             := "forbid-unless-resource-eq-doc2"
  , effect         := .forbid
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .unless
                        , body := .binaryApp .eq (.var .resource) (.lit (.entityUID (mkUID "Document" "doc2"))) }]
  }

-- Shape 24: unless { principal in Group::"viewers" } (unless + in)
private def permitUnlessPrincipalInViewers : Policy :=
  { id             := "permit-unless-principal-in-viewers"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .unless
                        , body := .binaryApp .mem (.var .principal) (.lit (.entityUID (mkUID "Group" "viewers"))) }]
  }

-- Shape 25: unless { resource is Photo } (unless + is type-guard)
private def permitUnlessResourceIsPhoto : Policy :=
  { id             := "permit-unless-resource-is-photo"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .unless
                        , body := .unaryApp (.is (mkEty "Photo")) (.var .resource) }]
  }

-- ── widening: extension / set / record / nested-attr shapes ──────
-- These are the four cedar-drt-flagged constructor classes.
-- Each uses an extension/set/record/nested-attr expression in a when body.
-- Soundness lemmas in CedarFull.Soundness.lean.

-- Shape 26: when { decimal("1.0") == decimal("1.0") }
private def permitWhenDecimalEqSelf : Policy :=
  { id             := "permit-when-decimal-eq-self"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .binaryApp .eq extDecimalLit extDecimalLit }]
  }

-- Shape 27: when { ip("10.0.0.1") == ip("10.0.0.1") }
private def permitWhenIpEqSelf : Policy :=
  { id             := "permit-when-ip-eq-self"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .binaryApp .eq extIpLit extIpLit }]
  }

-- Shape 28: when { principal in [User::"alice", User::"bob", User::"carol"] }
private def permitWhenPrincipalInSet : Policy :=
  { id             := "permit-when-principal-in-set"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .binaryApp .mem (.var .principal) setLitUserEntities }]
  }

-- Shape 29: when { {} has approved } (record literal in has)
private def permitWhenEmptyRecordHas : Policy :=
  { id             := "permit-when-empty-record-has"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .hasAttr recordEmptyLit "approved" }]
  }

-- Shape 30: when { {approved: true} has approved } (record literal in has)
private def permitWhenSingletonRecordHas : Policy :=
  { id             := "permit-when-singleton-record-has"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .hasAttr recordSingletonLit "approved" }]
  }

-- Shape 31: when { principal has address } (has on entity attr)
private def permitWhenPrincipalHasAddress : Policy :=
  { id             := "permit-when-principal-has-address"
  , effect         := .permit
  , principalScope := .principalScope (.is (mkEty "User"))
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .hasAttr (.var .principal) "address" }]
  }

-- Shape 32: when { principal has address && principal.address.street == "Main" }
-- Capability threading: `has address` adds the attribute capability that
-- lets the nested .address access typecheck in the AND right-arm.
private def permitWhenNestedAttrEq : Policy :=
  { id             := "permit-when-nested-attr-eq"
  , effect         := .permit
  , principalScope := .principalScope (.is (mkEty "User"))
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .and
                            (.hasAttr (.var .principal) "address")
                            (.binaryApp .eq nestedAttrLit (.lit (.string "Main"))) }]
  }

-- ── cedar-drt-targeted bug-hunt shapes ─────────────────────
-- Each shape exercises a constructor pair that prior cedar-drt
-- runs have flagged as disagreement-prone but the prior widening
-- (shapes 26-32) does not yet reach. Soundness lemmas in
-- CedarFull.Soundness; shape values are deterministic so the
-- per-tuple cost is the same as existing shapes.

-- Shape 33: when { setLitUserEntities.containsAll(setLitUserEntities) }
-- Always true semantically; exercises the .containsAll constructor
-- which is a distinct evaluator path from .mem (shape 28).
private def permitWhenSetContainsAllSelf : Policy :=
  { id             := "permit-when-set-containsAll-self"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .binaryApp .containsAll
                                    setLitUserEntities setLitUserEntities }]
  }

-- Shape 34: when { setLitUserEntities.contains(principal) }
-- Functionally equivalent to `principal in [User::"alice", ...]`
-- (shape 28) but lands on the .contains binary op rather than .mem.
-- cedar-drt has historically reported divergences between cedar-policy
-- and cedar-go on `in` vs `.contains` over single-element membership.
private def permitWhenSetContainsPrincipal : Policy :=
  { id             := "permit-when-set-contains-principal"
  , effect         := .permit
  , principalScope := .principalScope (.is (mkEty "User"))
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .binaryApp .contains
                                    setLitUserEntities (.var .principal) }]
  }

-- ── single-element set + .contains/.in isolation pair ──────
-- The 3-element setLitUserEntities (shapes 33-34) does not isolate the
-- cedar-drt-flagged single-membership divergence class. Shapes 35-36
-- use setLitSingletonAlice (the singleton [User::"alice"]) so any
-- disagreement between .contains-side and .mem-side can be
-- triangulated to the membership cardinality.

-- Shape 35: when { [User::"alice"].contains(principal) }
-- Single-element .contains. Probes the cedar-drt-flagged class
-- directly. The principal-is-User scope ensures the contains arg
-- typechecks as a (.entity User), matching the set's element type.
private def permitWhenSingletonContainsPrincipal : Policy :=
  { id             := "permit-when-singleton-contains-principal"
  , effect         := .permit
  , principalScope := .principalScope (.is (mkEty "User"))
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .binaryApp .contains
                                    setLitSingletonAlice (.var .principal) }]
  }

-- Shape 36: when { principal in [User::"alice"] }
-- Same predicate as shape 35 but routed through .mem instead of
-- .contains. Pair lets us isolate whether a disagreement (if any
-- ever surfaces) sits on the .contains side or the .mem side.
private def permitWhenSingletonInPrincipal : Policy :=
  { id             := "permit-when-singleton-in-principal"
  , effect         := .permit
  , principalScope := .principalScope (.is (mkEty "User"))
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .binaryApp .mem
                                    (.var .principal) setLitSingletonAlice }]
  }

-- ── parser-level string-form drift probes ─────────────
-- Shapes 33-36 cover evaluator-path divergence classes. A separate
-- residual sits at the parser level: cedar-policy and cedar-go run
-- distinct Decimal + IPAddr parsers. These shapes use string forms
-- that differ from the canonical extDecimalLit + extIpLit values to
-- probe whether cross-form equality stays in agreement.

-- Shape 37: when { decimal("1.0") == decimal("1.000") }
-- Same value semantically; different string forms. cedar-policy and
-- cedar-go independently parse + normalize Decimal; cross-form
-- equality probes whether the two parsers agree on canonical form.
private def permitWhenDecimalCrossPrecisionEq : Policy :=
  { id             := "permit-when-decimal-cross-precision-eq"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .binaryApp .eq
                                    extDecimalLit extDecimalLitThousandths }]
  }

-- Shape 38: when { ip("::1") == ip("::1") }
-- IPv6 self-equality. Same .ext .ipaddr type as IPv4 (extIpLit) but
-- exercises the IPv6 parser path. cedar-go's IPAddr parser had
-- historical drift on IPv6 zero-compression forms.
private def permitWhenIpV6EqSelf : Policy :=
  { id             := "permit-when-ipv6-eq-self"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .binaryApp .eq
                                    extIpV6LocalhostLit extIpV6LocalhostLit }]
  }

-- ── Novelty sweep: shapes 39-42 ───────────────────
-- Four constructor classes that the 38-shape grammar does not yet
-- exercise. Each is one-line + a sorry-stubbed wellTypedAt lemma per
-- the existing widening-deferral pattern. Diff harness re-runs at
-- N=10k against the wider 42-shape grammar; soundness lemmas live in
-- CedarFull.Soundness.

-- Shape 39: when { principal in [] }
-- Empty-set membership. The 38-shape grammar covers .mem against
-- 1-element and 3-element sets (shapes 28, 35); the empty set is a
-- distinct evaluator path: cedar-policy and cedar-go must agree that
-- `principal in []` evaluates to false unconditionally.
private def permitWhenPrincipalInEmptySet : Policy :=
  { id             := "permit-when-principal-in-empty-set"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .binaryApp .mem (.var .principal) (.set []) }]
  }

-- Shape 40: when { {approved: true, denied: false} has approved }
-- Multi-key record literal. The 38-shape grammar covers 0-key
-- (shape 29) and 1-key (shape 30) records; the 2-key case exercises
-- typeOfRecord's multi-attribute LUB and the .hasAttr evaluator's
-- record-key lookup on a record with siblings.
private def recordTwoKeyLit : Expr :=
  .record [ ("approved", .lit (.bool true))
          , ("denied",   .lit (.bool false))
          ]

private def permitWhenTwoKeyRecordHas : Policy :=
  { id             := "permit-when-two-key-record-has"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .hasAttr recordTwoKeyLit "approved" }]
  }

-- Shape 41: when { !(principal == User::"alice") }
-- Boolean negation on an equality. The 38-shape grammar uses
-- .unaryApp .is (shapes 8-10, 18-20, 25); .not is the second unary
-- operator and exercises the boolean-inversion evaluator branch.
private def permitWhenNotPrincipalEqAlice : Policy :=
  { id             := "permit-when-not-principal-eq-alice"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .unaryApp .not
                                    (.binaryApp .eq
                                      (.var .principal)
                                      (.lit (.entityUID (mkUID "User" "alice")))) }]
  }

-- Shape 42: when { (1 + 1) == 2 }
-- Integer arithmetic in a when body. .add on int literals is a
-- distinct evaluator path that exercises both typecheckers'
-- arithmetic branches and integer-overflow handling.
private def permitWhenIntArithEqTwo : Policy :=
  { id             := "permit-when-int-arith-eq-two"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when
                        , body := .binaryApp .eq
                                    (.binaryApp .add
                                      (.lit (.int 1))
                                      (.lit (.int 1)))
                                    (.lit (.int 2)) }]
  }

/-- Random Cedar policy generator (Stage 5: scope randomization).
    Mike Hicks's "load-bearing" critique was that the prior PolicyGen
    pinned 41 specific scope/condition combinations as fixtures. The
    new layout drops the 24 generic scope-only / condition-only fixtures
    (shapes 1-25 in the prior numbering), keeping only the 17 EDGE-CASE
    fixtures that exercise specific known bug classes the random arm
    does not reliably reproduce: extension-literal parser drift
    (decimal, ip, decimal-precision, IPv6), record-literal edges
    (empty, singleton, two-key, has-attr, nested-attr), set-literal
    edges (containsAll, contains, singleton-contains, singleton-in,
    empty-set-mem), and the .not / .add isolation pairs from §VIII.
    The bulk of policies now flow through `genRandomPolicy` which
    enumerates the full 5-variant scope cross-product per role
    (.any / .eq / .mem / .is / .isMem) plus actionInAny, with
    permit/forbid effect and empty/when/unless condition. -/
def genPolicy (_ : Schema) : Gen Policy :=
  -- §VIII / bug-hunt edge-case fixtures (kept because the random arm
  -- doesn't reliably reproduce these specific shapes):
  Gen.pick (pure permitWhenDecimalEqSelf)            -- B2 ext drift
  (Gen.pick (pure permitWhenIpEqSelf)                -- B2 ext drift
  (Gen.pick (pure permitWhenPrincipalInSet)          -- principal in [uid…]
  (Gen.pick (pure permitWhenEmptyRecordHas)          -- {} has k
  (Gen.pick (pure permitWhenSingletonRecordHas)      -- {k:v} has k
  (Gen.pick (pure permitWhenPrincipalHasAddress)     -- entity-attr has
  (Gen.pick (pure permitWhenNestedAttrEq)            -- nested attr
  (Gen.pick (pure permitWhenSetContainsAllSelf)      -- set.containsAll
  (Gen.pick (pure permitWhenSetContainsPrincipal)    -- set.contains
  (Gen.pick (pure permitWhenSingletonContainsPrincipal)
  (Gen.pick (pure permitWhenSingletonInPrincipal)
  (Gen.pick (pure permitWhenDecimalCrossPrecisionEq) -- decimal precision drift
  (Gen.pick (pure permitWhenIpV6EqSelf)              -- IPv6 drift
  (Gen.pick (pure permitWhenPrincipalInEmptySet)     -- principal in []
  (Gen.pick (pure permitWhenTwoKeyRecordHas)         -- two-key record
  (Gen.pick (pure permitWhenNotPrincipalEqAlice)     -- !
  (Gen.pick (pure permitWhenIntArithEqTwo)           -- int arith
  -- The load-bearing change: random scope/effect/condition policy.
  -- Replaces the prior 24 hardcoded generic templates AND the prior
  -- 5 explicit "policyWith*Cond" wired arms (those defs remain in
  -- the file as test targets but no longer flow through genPolicy).
            genRandomPolicy))))))))))))))))

-- ── genTuple ────────────────────────────────────────────────────────

/-- The top-level generator: produces (Schema, Request, Policy) triples.
    Schema is always fixedSchema; Request and Policy are independently sampled. -/
def genTuple : Gen (Schema × Request × Policy) :=
  do let schema ← genSchema
     let req    ← genRequest schema
     let pol    ← genPolicy schema
     pure (schema, req, pol)

-- ── Cedar text serializers ───────────────────────────────────────────
--
-- These convert Cedar.Spec.{Policy,Request} to Cedar text format
-- so the MeasureDiff driver can emit JSON for the Python diff runner.

/-- Serialize a Cedar EntityUID to Cedar text: `Type::"eid"`. -/
def uidToText (uid : EntityUID) : String :=
  s!"{uid.ty}::\"{uid.eid}\""

/-- Serialize a Cedar Scope to text (for principal or resource slot). -/
def scopeToText (varName : String) : Scope → String
  | .any       => varName
  | .eq uid    => s!"{varName} == {uidToText uid}"
  | .mem uid   => s!"{varName} in {uidToText uid}"
  | .is ety    => s!"{varName} is {ety}"
  | .isMem ety uid => s!"{varName} is {ety} && {varName} in {uidToText uid}"

/-- Serialize an ActionScope to text. -/
def actionScopeToText : ActionScope → String
  | .actionScope s => scopeToText "action" s
  | .actionInAny uids =>
    let joined := String.intercalate ", " (uids.map uidToText)
    s!"action in [{joined}]"

/-- Serialize an ExtFun to its Cedar surface name. -/
def extFunToText : ExtFun → String
  | .decimal           => "decimal"
  | .ip                => "ip"
  | .datetime          => "datetime"
  | .duration          => "duration"
  | .lessThan          => "lessThan"
  | .lessThanOrEqual   => "lessThanOrEqual"
  | .greaterThan       => "greaterThan"
  | .greaterThanOrEqual => "greaterThanOrEqual"
  | .isIpv4            => "isIpv4"
  | .isIpv6            => "isIpv6"
  | .isLoopback        => "isLoopback"
  | .isMulticast       => "isMulticast"
  | .isInRange         => "isInRange"
  | .offset            => "offset"
  | .durationSince     => "durationSince"
  | .toDate            => "toDate"
  | .toTime            => "toTime"
  | .toMilliseconds    => "toMilliseconds"
  | .toSeconds         => "toSeconds"
  | .toMinutes         => "toMinutes"
  | .toHours           => "toHours"
  | .toDays            => "toDays"

/-- Serialize a Cedar Expr to Cedar text.  V2 §8 widened: serialises
    set/record/call constructors (extension functions, set/record literals). -/
partial def exprToText : Expr → String
  | .lit (.bool true)          => "true"
  | .lit (.bool false)         => "false"
  | .lit (.int i)              => s!"{i.toInt}"
  | .lit (.string s)           => s!"\"{s}\""
  | .lit (.entityUID uid)      => uidToText uid
  | .var .principal            => "principal"
  | .var .action               => "action"
  | .var .resource             => "resource"
  | .var .context              => "context"
  | .and a b                   => s!"({exprToText a} && {exprToText b})"
  | .or  a b                   => s!"({exprToText a} || {exprToText b})"
  | .ite c t f                 => s!"(if {exprToText c} then {exprToText t} else {exprToText f})"
  | .unaryApp .not a           => s!"(!{exprToText a})"
  | .unaryApp .neg a           => s!"(-{exprToText a})"
  | .unaryApp .isEmpty a       => s!"({exprToText a}).isEmpty()"
  | .unaryApp (.like _) a      => s!"({exprToText a} like \"*\")"
  | .unaryApp (.is ety) a      => s!"({exprToText a} is {ety})"
  | .binaryApp .add a b        => s!"({exprToText a} + {exprToText b})"
  | .binaryApp .sub a b        => s!"({exprToText a} - {exprToText b})"
  | .binaryApp .mul a b        => s!"({exprToText a} * {exprToText b})"
  | .binaryApp .eq  a b        => s!"({exprToText a} == {exprToText b})"
  | .binaryApp .mem a b        => s!"({exprToText a} in {exprToText b})"
  | .binaryApp .less a b       => s!"({exprToText a} < {exprToText b})"
  | .binaryApp .lessEq a b     => s!"({exprToText a} <= {exprToText b})"
  | .binaryApp .contains a b   => s!"({exprToText a}.contains({exprToText b}))"
  | .binaryApp .containsAll a b => s!"({exprToText a}.containsAll({exprToText b}))"
  | .binaryApp .containsAny a b => s!"({exprToText a}.containsAny({exprToText b}))"
  | .binaryApp .hasTag a b     => s!"({exprToText a} hasTag {exprToText b})"
  | .binaryApp .getTag a b     => s!"({exprToText a} getTag {exprToText b})"
  | .hasAttr e attr            => s!"({exprToText e} has {attr})"
  | .getAttr e attr            => s!"({exprToText e}.{attr})"
  -- Set literal: [e1, e2, ...]
  | .set xs                    =>
    let elems := xs.map exprToText
    s!"[{String.intercalate ", " elems}]"
  -- Record literal: {a1: e1, a2: e2, ...}
  | .record axs                =>
    let pairs := axs.map (fun (a, e) => s!"\"{a}\": {exprToText e}")
    s!"\{{String.intercalate ", " pairs}}"
  -- Extension function call: fn(arg1, arg2, ...)
  | .call fn args              =>
    let argStrs := args.map exprToText
    s!"{extFunToText fn}({String.intercalate ", " argStrs})"

/-- Serialize a Cedar.Spec.Condition to `when { <expr> }` or `unless { <expr> }`. -/
def conditionToText (c : Condition) : String :=
  let bodyText := exprToText c.body
  match c.kind with
  | .when   => "when { " ++ bodyText ++ " }"
  | .unless => "unless { " ++ bodyText ++ " }"

/-- Serialize a Cedar.Spec.Policy to Cedar text (single-policy .cedar format).
    Uses space-separated scope (no newlines) for clean tab-separated output. -/
def policyToText (p : Policy) : String :=
  let effect := match p.effect with | .permit => "permit" | .forbid => "forbid"
  let ps := scopeToText "principal" p.principalScope.scope
  let as_ := actionScopeToText p.actionScope
  let rs := scopeToText "resource" p.resourceScope.scope
  let conds := p.condition.map conditionToText
  let condStr := match conds with | [] => "" | _ => " " ++ String.intercalate " " conds
  s!"{effect}({ps}, {as_}, {rs}){condStr};"

/-- Serialize a Cedar.Spec.Request: returns "principal TAB action TAB resource" fields. -/
def requestToFields (req : Request) : String × String × String :=
  let p := req.principal
  let a := req.action
  let r := req.resource
  (s!"{p.ty}::{p.eid}", s!"{a.ty}::{a.eid}", s!"{r.ty}::{r.eid}")

/-- Emit one tab-separated line per tuple:
    idx TAB principal TAB action TAB resource TAB policyText
    Python parses this to avoid nested JSON escaping complexity. -/
def tupleToLine (idx : Nat) (_ : Schema) (req : Request) (pol : Policy) : String :=
  let p := req.principal
  let a := req.action
  let r := req.resource
  let pol' := (policyToText pol).replace "\t" " "
  s!"{idx}\t{p.ty}::{p.eid}\t{a.ty}::{a.eid}\t{r.ty}::{r.eid}\t{pol'}"

end CedarFull.PolicyGen
