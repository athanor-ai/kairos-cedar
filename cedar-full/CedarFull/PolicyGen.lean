/-
  CedarFull.PolicyGen: a minimal, static-schema Policy+Schema+Request generator.

  Paper §8 setup: each run draws N tuples from the generator. This module
  provides `genTuple : Gen (Cedar.Spec.Schema × Cedar.Spec.Request × Cedar.Spec.Policy)`
  using a fixed 3-entity-type / 3-action schema (User, Document, Photo; view, edit, admin).

  Design rationale for N=1000 first pass:
    • Schema is fixed (a single hardcoded Schema value); schema diversity is future work.
    • Request varies over 9 (principal × action × resource) combinations.
    • Policy varies over 8 hand-picked shapes (permit-any, forbid-any,
      permit-if-principal-eq, permit-if-resource-eq, forbid-if-resource-eq,
      permit-for-action, forbid-for-action, permit-with-condition).
      Total support size: 9 × 8 = 72 distinct (request, policy) pairs.
      At N=1000 we sample with replacement across this 72-element pool.

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
--   entity Document;
--   entity Photo;
--
--   action view appliesTo { principal: User, resource: [Document, Photo] };
--   action edit appliesTo { principal: User, resource: [Document, Photo] };
--   action admin appliesTo { principal: User, resource: [Document, Photo] };

/-- The fixed entity schema: User, Document, Photo with no attributes or ancestors. -/
def fixedEntitySchema : EntitySchema :=
  Map.make
    [ (mkEty "User",     EntitySchemaEntry.standard { ancestors := Set.empty, attrs := Map.empty, tags := none })
    , (mkEty "Document", EntitySchemaEntry.standard { ancestors := Set.empty, attrs := Map.empty, tags := none })
    , (mkEty "Photo",    EntitySchemaEntry.standard { ancestors := Set.empty, attrs := Map.empty, tags := none })
    ]

/-- The fixed action schema: view, edit, admin — each applies to User × {Document, Photo}. -/
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

private def principals : List EntityUID :=
  [ mkUID "User" "alice", mkUID "User" "bob", mkUID "User" "carol" ]

private def actions : List EntityUID :=
  [ mkUID "Action" "view", mkUID "Action" "edit", mkUID "Action" "admin" ]

private def resources : List EntityUID :=
  [ mkUID "Document" "doc1", mkUID "Photo" "photo1", mkUID "Document" "doc2" ]

/-- Lift a list of values into a Gen that returns any one of them. -/
private def genAny {α : Type} (xs : List α) : Gen α := ⟨xs⟩

/-- Generate a request conditioned on `fixedSchema`.
    Picks from 27 (principal, action, resource) triples; context is always empty. -/
def genRequest (_ : Schema) : Gen Request :=
  do let p ← genAny principals
     let a ← genAny actions
     let r ← genAny resources
     pure { principal := p, action := a, resource := r, context := Map.empty }

-- ── genPolicy ───────────────────────────────────────────────────────
--
-- 8 hand-picked policy shapes, each a Cedar.Spec.Policy.
-- The condition body is either a literal (for flat shapes) or uses
-- genWellTyped (for the condition-with-expr shape).

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
private def policyWithWhenCond (condExpr : Expr) : Policy :=
  { id             := "permit-with-cond"
  , effect         := .permit
  , principalScope := .principalScope .any
  , actionScope    := .actionScope .any
  , resourceScope  := .resourceScope .any
  , condition      := [{ kind := .when, body := condExpr }]
  }

/-- Generate a Cedar.Spec.Policy. 8 shapes; the last uses genWellTyped for its condition. -/
def genPolicy (_ : Schema) : Gen Policy :=
  Gen.pick (pure permitAny)
  (Gen.pick (pure forbidAny)
  (Gen.pick (pure permitIfPrincipalEqAlice)
  (Gen.pick (pure permitIfPrincipalEqBob)
  (Gen.pick (pure forbidIfResourceEqDoc1)
  (Gen.pick (pure permitForActionView)
  (Gen.pick (pure forbidForActionAdmin)
            -- 8th shape: permit(any, any, any) when {<well-typed bool expr>}
            (do let condExpr ← genWellTyped fixedEnv (.bool .anyBool)
                pure (policyWithWhenCond condExpr))))))))

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

/-- Serialize a Cedar Expr to a simple boolean expression text.
    Only covers the constructors that genWellTyped can produce:
    lit(bool), var, and, or, ite, binaryApp(add), unaryApp(neg/not). -/
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
  | .set _                     => "false"   -- Phase B: unsupported, fallback
  | .record _                  => "false"   -- Phase B: unsupported, fallback
  | .call _ _                  => "false"   -- Phase B: unsupported, fallback

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
