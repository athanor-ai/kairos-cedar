/-
  RegoFull.PolicyGen: a static generator for well-typed Rego rule shapes.

  Mirrors CedarFull.PolicyGen in structure: a fixed schema plus a
  list of named policy shapes.

  Schema (analogous to Cedar's fixed entity schema):
    input : {
      role    : string,
      level   : number,
      groups  : array<string>,
      region  : string,
      active  : bool,
      user    : { role: string, tier: number }
    }

  Eight (8) well-typed rule shapes:
    Shape 1: allow if { input.role == "admin" }
    Shape 2: allow if { input.level > 3 }
    Shape 3: allow if { input.role in {"admin", "editor"} }
    Shape 4: allow if { input.active }
    Shape 5: allow if { input.role == "admin"; input.level > 3 }   (conjunction)
    Shape 6: allow if { input.groups[_] == "ops" }                  (array membership)
    Shape 7: allow if { not input.active; input.role == "viewer" } (negation)
    Shape 8: allow if { input.user.role == "admin" }                (nested access)

  All shapes are well-typed under `fixedSchema` by construction
  (witnessed by `HasType` derivations in Soundness.lean).

  The generator is a static pool (no randomness): the diff runner samples
  all 8 shapes against multiple input documents.
-/

import RegoBridge

open Rego.Spec
open RegoBridge

namespace RegoFull.PolicyGen

/-── Fixed schema ────────────────────────────────────────────────────────────-/

/-- The fixed schema used across all generated rules.

    OPA CLI equivalent (JSON Schema):
    {
      "type": "object",
      "properties": {
        "role":    { "type": "string" },
        "level":   { "type": "number" },
        "groups":  { "type": "array", "items": { "type": "string" } },
        "region":  { "type": "string" },
        "active":  { "type": "boolean" },
        "user":    { "type": "object",
                     "properties": {
                       "role": { "type": "string" },
                       "tier": { "type": "number" }
                     }}
      }
    }
-/
def fixedSchema : Schema :=
  [ ("role",   .scalar .string)
  , ("level",  .scalar .number)
  , ("groups", .array (.scalar .string))
  , ("region", .scalar .string)
  , ("active", .scalar .bool)
  , ("user",   .object [("role", .scalar .string), ("tier", .scalar .number)])
  ]

/-── Minimal Gen type (mirrors CedarFull.Expr.Gen) ───────────────────────────-/

structure Gen (α : Type) where
  val : List α

namespace Gen

def pick (x y : Gen α) : Gen α := ⟨x.val ++ y.val⟩
def ret  (a : α)       : Gen α := ⟨[a]⟩

def support {α} (g : Gen α) (a : α) : Prop := a ∈ g.val

instance : Monad Gen where
  pure a   := ⟨[a]⟩
  bind x f := ⟨x.val.flatMap (fun a => (f a).val)⟩

end Gen

/-── Policy shape record ─────────────────────────────────────────────────────-/

/-- A named Rego rule shape: a policy body expression plus a display name. -/
structure PolicyShape where
  name : String
  body : Expr

/-── Shape 1: input.role == "admin" ─────────────────────────────────────────-/
def shape1 : PolicyShape :=
  { name := "role-eq-admin"
  , body := .cmp .eq (.input_attr "role") (.lit (.string "admin"))
  }

/-── Shape 2: input.level > 3 ────────────────────────────────────────────────-/
def shape2 : PolicyShape :=
  { name := "level-gt-3"
  , body := .cmp .gt (.input_attr "level") (.lit (.number 3))
  }

/-── Shape 3: input.role in {"admin", "editor"} ──────────────────────────────-/
def shape3 : PolicyShape :=
  { name := "role-in-set"
  , body := .in_set (.input_attr "role") [.string "admin", .string "editor"]
  }

/-── Shape 4: input.active ───────────────────────────────────────────────────-/
-- NOTE: in Rego, `allow if { input.active }` is valid only if `input.active`
-- is boolean-valued. Our schema declares it as `scalar bool`, so this is
-- well-typed. But the OPA type checker treats this as a *reference* (not a
-- comparison), meaning it evaluates to the value of input.active directly.
-- This is a known subtle point: OPA requires the expression to evaluate to
-- true/false rather than undefined. We model it as a comparison to true.
def shape4 : PolicyShape :=
  { name := "active-is-true"
  , body := .cmp .eq (.input_attr "active") (.lit (.bool true))
  }

/-── Shape 5: input.role == "admin", input.level > 3 (conjunction) ───────────-/
def shape5 : PolicyShape :=
  { name := "role-admin-and-level-gt-3"
  , body := .and_
      (.cmp .eq  (.input_attr "role")  (.lit (.string "admin")))
      (.cmp .gt  (.input_attr "level") (.lit (.number 3)))
  }

/-── Shape 6: input.groups[_] == "ops" (array membership) ───────────────────-/
def shape6 : PolicyShape :=
  { name := "groups-contains-ops"
  , body := .in_arr "groups" (.lit (.string "ops"))
  }

/-── Shape 7: not input.active; input.role == "viewer" ───────────────────────-/
-- Conjunction of not(active) and role == "viewer".
def shape7 : PolicyShape :=
  { name := "not-active-and-role-viewer"
  , body := .and_
      (.not_ (.cmp .eq (.input_attr "active") (.lit (.bool true))))
      (.cmp .eq (.input_attr "role") (.lit (.string "viewer")))
  }

/-── Shape 8: input.user.role == "admin" (nested attribute access) ───────────-/
def shape8 : PolicyShape :=
  { name := "user-role-eq-admin"
  , body := .cmp .eq (.nested "user" "role") (.lit (.string "admin"))
  }

/-── Generator ───────────────────────────────────────────────────────────────-/

/-- The static pool of all 8 policy shapes. -/
def allShapes : List PolicyShape :=
  [shape1, shape2, shape3, shape4, shape5, shape6, shape7, shape8]

/-- Generator: returns all shapes (deterministic pool, not random). -/
def genPolicy : Gen PolicyShape :=
  ⟨allShapes⟩

/-── Input documents ─────────────────────────────────────────────────────────-/

/-- Sample input documents for the differential test.
    10 documents covering the interesting corners of the schema. -/
def sampleInputs : List (String × Input) :=
  [ ("admin-level5"
    , [ ("role",   .string "admin")
      , ("level",  .number 5)
      , ("groups", .array [.string "ops", .string "dev"])
      , ("region", .string "us-east")
      , ("active", .bool true)
      , ("user",   .object [("role", .string "admin"), ("tier", .number 2)])
      ])
  , ("editor-level2"
    , [ ("role",   .string "editor")
      , ("level",  .number 2)
      , ("groups", .array [.string "dev"])
      , ("region", .string "eu-west")
      , ("active", .bool true)
      , ("user",   .object [("role", .string "editor"), ("tier", .number 1)])
      ])
  , ("viewer-level0"
    , [ ("role",   .string "viewer")
      , ("level",  .number 0)
      , ("groups", .array [])
      , ("region", .string "ap-east")
      , ("active", .bool false)
      , ("user",   .object [("role", .string "viewer"), ("tier", .number 0)])
      ])
  , ("admin-level3-boundary"
    , [ ("role",   .string "admin")
      , ("level",  .number 3)        -- exactly 3: gt-3 should be false
      , ("groups", .array [.string "ops"])
      , ("region", .string "us-west")
      , ("active", .bool true)
      , ("user",   .object [("role", .string "admin"), ("tier", .number 1)])
      ])
  , ("editor-no-groups"
    , [ ("role",   .string "editor")
      , ("level",  .number 4)
      , ("groups", .array [])        -- empty groups: in_arr should be false
      , ("region", .string "us-east")
      , ("active", .bool true)
      , ("user",   .object [("role", .string "editor"), ("tier", .number 2)])
      ])
  , ("viewer-inactive"
    , [ ("role",   .string "viewer")
      , ("level",  .number 1)
      , ("groups", .array [.string "ops"])
      , ("region", .string "us-east")
      , ("active", .bool false)      -- inactive viewer: shape7 should fire
      , ("user",   .object [("role", .string "viewer"), ("tier", .number 0)])
      ])
  , ("missing-level"                 -- level field absent
    , [ ("role",   .string "admin")
      , ("groups", .array [.string "ops"])
      , ("region", .string "us-east")
      , ("active", .bool true)
      , ("user",   .object [("role", .string "admin"), ("tier", .number 1)])
      ])
  , ("null-role"                     -- role is present but is null
    , [ ("role",   .null)
      , ("level",  .number 5)
      , ("groups", .array [.string "ops"])
      , ("region", .string "us-east")
      , ("active", .bool true)
      , ("user",   .object [("role", .string "admin"), ("tier", .number 1)])
      ])
  , ("nested-user-admin"
    , [ ("role",   .string "viewer")
      , ("level",  .number 1)
      , ("groups", .array [])
      , ("region", .string "us-east")
      , ("active", .bool false)
      , ("user",   .object [("role", .string "admin"), ("tier", .number 3)])
      ])
  , ("level-negative"                -- negative number: gt-3 should be false
    , [ ("role",   .string "admin")
      , ("level",  .number (-1))
      , ("groups", .array [.string "ops"])
      , ("region", .string "us-east")
      , ("active", .bool true)
      , ("user",   .object [("role", .string "admin"), ("tier", .number 1)])
      ])
  ]

/-── Serialisers ─────────────────────────────────────────────────────────────-/

/-- Serialise a Literal to a Rego/JSON string fragment. -/
def litToRego : Literal → String
  | .bool true   => "true"
  | .bool false  => "false"
  | .number n    => s!"{n}"
  | .string s    => s!"\"{s}\""
  | .null        => "null"

/-- Serialise a CmpOp to Rego syntax. -/
def cmpOpToRego : CmpOp → String
  | .eq  => "=="
  | .neq => "!="
  | .lt  => "<"
  | .le  => "<="
  | .gt  => ">"
  | .ge  => ">="

/-- Serialise an Expr to a Rego body fragment. -/
def exprToRego : Expr → String
  | .lit l               => litToRego l
  | .input_attr key      => s!"input.{key}"
  | .nested key sub      => s!"input.{key}.{sub}"
  | .cmp op e1 e2        =>
      s!"{exprToRego e1} {cmpOpToRego op} {exprToRego e2}"
  | .in_set e vs         =>
      let setStr := "{" ++ String.intercalate ", " (vs.map litToRego) ++ "}"
      s!"{exprToRego e} in {setStr}"
  | .in_arr key e2       =>
      -- Rego array membership: some x in input.key { x == e2 }
      -- Simplified form using [_]: input.key[_] == e2
      s!"input.{key}[_] == {exprToRego e2}"
  | .and_ e1 e2          =>
      -- Rego conjunction: separate body expressions
      s!"{exprToRego e1}\n    {exprToRego e2}"
  | .or_ e1 e2           =>
      -- Rego disjunction: two separate rules; serialised as `e1` in first body.
      -- For the generator we use the simpler OR form inline where possible.
      s!"({exprToRego e1}) or ({exprToRego e2})"
  | .not_ e              =>
      s!"not ({exprToRego e})"

/-- Emit a complete Rego policy file for a shape. -/
def shapeToRegoPolicy (shape : PolicyShape) : String :=
  let body := exprToRego shape.body
  s!"package kairos\n\nallow if \{\n    {body}\n}\n"

/-- Serialise a Value to JSON. -/
partial def valueToJson : Value → String
  | .bool true   => "true"
  | .bool false  => "false"
  | .number n    => s!"{n}"
  | .string s    => s!"\"{s}\""
  | .null        => "null"
  | .array vs    =>
      "[" ++ String.intercalate "," (vs.map valueToJson) ++ "]"
  | .set_ vs     =>
      "[" ++ String.intercalate "," (vs.map valueToJson) ++ "]"
  | .object kvs  =>
      let pairs := kvs.map (fun (k, v) => s!"\"{k}\":{valueToJson v}")
      "{" ++ String.intercalate "," pairs ++ "}"

/-- Serialise an Input document to JSON. -/
def inputToJson (inp : Input) : String :=
  let pairs := inp.map (fun (k, v) => s!"\"{k}\":{valueToJson v}")
  "{" ++ String.intercalate "," pairs ++ "}"

/-- Emit a tab-separated line for the diff runner:
    shape_name TAB input_name TAB spec_result TAB policy_rego TAB input_json
    spec_result: "true" | "false" | "undefined" -/
def tupleToLine (shape : PolicyShape) (inputName : String) (inp : Input) : String :=
  let specResult :=
    match Rego.Spec.eval inp shape.body with
    | some true  => "true"
    | some false => "false"
    | none       => "undefined"
  -- Escape newlines to \n so the whole line fits on one tab-separated row
  let policyRego := ((shapeToRegoPolicy shape).replace "\t" " ").replace "\n" "\\n"
  let inputJson  := inputToJson inp
  s!"{shape.name}\t{inputName}\t{specResult}\t{policyRego}\t{inputJson}"

end RegoFull.PolicyGen
