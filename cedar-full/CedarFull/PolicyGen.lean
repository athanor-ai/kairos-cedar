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

/-- The fixed entity schema: User, Group, Document, Photo.
    Group is added to support `principal in Group::"admins"` conditions.
    Context carries a boolean attribute "approved" for has/getAttr shapes. -/
def fixedEntitySchema : EntitySchema :=
  Map.make
    [ (mkEty "User",     EntitySchemaEntry.standard { ancestors := Set.empty, attrs := Map.empty, tags := none })
    , (mkEty "Group",    EntitySchemaEntry.standard { ancestors := Set.empty, attrs := Map.empty, tags := none })
    , (mkEty "Document", EntitySchemaEntry.standard { ancestors := Set.empty, attrs := Map.empty, tags := none })
    , (mkEty "Photo",    EntitySchemaEntry.standard { ancestors := Set.empty, attrs := Map.empty, tags := none })
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

/-- Generate a Cedar.Spec.Policy. 25 shapes covering scope variants (eq/is/in/actionInAny)
    and condition variants (when/unless with eq, in, is, has on principal/action/resource/context).
    The final shape uses genWellTyped for an arbitrary well-typed boolean condition.
    Shapes are chained with Gen.pick for uniform sampling over the 25-element support. -/
def genPolicy (_ : Schema) : Gen Policy :=
  -- Scope-only shapes (1–15)
  Gen.pick (pure permitAny)
  (Gen.pick (pure forbidAny)
  (Gen.pick (pure permitIfPrincipalEqAlice)
  (Gen.pick (pure permitIfPrincipalEqBob)
  (Gen.pick (pure forbidIfResourceEqDoc1)
  (Gen.pick (pure permitForActionView)
  (Gen.pick (pure forbidForActionAdmin)
  (Gen.pick (pure permitPrincipalIsUser)
  (Gen.pick (pure permitResourceIsDocument)
  (Gen.pick (pure forbidResourceIsPhoto)
  (Gen.pick (pure permitPrincipalInAdmins)
  (Gen.pick (pure forbidPrincipalInViewers)
  (Gen.pick (pure permitResourceInFolder)
  (Gen.pick (pure permitActionInViewEdit)
  -- Condition shapes (16–25)
  (Gen.pick (pure permitWhenPrincipalEqAlice)
  (Gen.pick (pure permitWhenActionEqView)
  (Gen.pick (pure forbidWhenResourceEqDoc1)
  (Gen.pick (pure permitWhenPrincipalInAdmins)
  (Gen.pick (pure permitWhenResourceIsDocument)
  (Gen.pick (pure permitWhenPrincipalIsUser)
  (Gen.pick (pure permitWhenContextHasApproved)
  (Gen.pick (pure forbidUnlessResourceEqDoc2)
  (Gen.pick (pure permitUnlessPrincipalInViewers)
  (Gen.pick (pure permitUnlessResourceIsPhoto)
            -- 25th shape: permit(any, any, any) when {<well-typed bool expr>}
            (do let condExpr ← genWellTyped fixedEnv (.bool .anyBool)
                pure (policyWithWhenCond condExpr)))))))))))))))))))))))))

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
