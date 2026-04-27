# OPA/Rego Bridge Design

*Status: Phase 1 (research) + Phase 2 (bridge) + Phase 3 (diff test): all complete.*
*Bugs found: 2. Reproducers at `experiments/phase_k_opa_diff/reproducers/`.*

## 1. Motivation

The kairos-cedar paper's title ("Authorization Engines") claims the
Lean-bridge pipeline transfers to other authorisation DSLs beyond Cedar.
Section IX hand-waves this. Applying the same pipeline to OPA/Rego
converts that claim from philosophical to empirical.



## 2. Rego Subset Selected

We mechanise the **simple boolean-rule core** of Rego: rules of the form

```rego
allow if {
    <body>
}
```

where `<body>` is a conjunction of conditions over `input.*` fields,
drawn from the following grammar:

```
Expr ::=
  | lit b | lit n | lit s | lit null          (scalar literals)
  | input.<key>                                (top-level attribute access)
  | input.<key>.<subkey>                       (one level of nesting)
  | Expr == Expr | Expr != Expr               (equality)
  | Expr < Expr | Expr <= Expr                (ordered, number only)
  | Expr > Expr | Expr >= Expr
  | Expr in { lit₁, lit₂, ... }              (set membership)
  | input.<key>[_] == Expr                    (array membership)
  | Expr ∧ Expr                               (Rego conjunction: comma)
  | Expr ∨ Expr                               (Rego disjunction: semicolon)
  | not Expr                                   (negation)
```

**Example policies in scope:**

```rego
allow if { input.role == "admin" }
allow if { input.level > 3 }
allow if { input.role in {"admin", "editor"} }
allow if { input.groups[_] == "ops" }
allow if { not (input.active == true); input.role == "viewer" }
allow if { input.user.role == "admin" }
```

**Out of scope (future work):**
- Comprehensions (set/array/object comprehensions)
- User-defined functions
- Partial rules / incremental definitions
- `with` keyword (input substitution)
- `import rego.v1` / `import future.keywords` features

This subset is analogous to Cedar's "permit + when" core: the smallest
productive fragment of the language sufficient to write real access-control
policies and exercise the type checker.



## 3. Lean Type System

The formal type system is in `opa-bridge/RegoBridge/Spec/Expr.lean`.

### 3.1 Types

```
ScalarType ::= bool | number | string | null

RegoType ::=
  | scalar ScalarType
  | array RegoType          -- homogeneous array
  | set_ RegoType           -- homogeneous set
  | object [(String × RegoType)]   -- fixed-key object
  | any_                    -- schema-free / dynamic
```

### 3.2 Schema

A `Schema` is `List (String × RegoType)`: a mapping from `input` field
names to their declared types. Analogous to Cedar's `TypeEnv` for the
request type.

### 3.3 Typing Judgments

The relation `HasType : Schema → Expr → RegoType → Prop` is an inductive
relation with 15 constructors:

| Rule         | Conclusion                              | Condition |
|--------------|-----------------------------------------|-----------|
| `lit_bool`   | `σ ⊢ lit (bool b) : scalar bool`       |: |
| `lit_number` | `σ ⊢ lit (number n) : scalar number`   |: |
| `lit_string` | `σ ⊢ lit (string s) : scalar string`   |: |
| `lit_null`   | `σ ⊢ lit null : scalar null`           |: |
| `attr_typed` | `σ ⊢ input.key : τ`                    | `σ(key) = τ` |
| `attr_any`   | `σ ⊢ input.key : any_`                 | `key ∉ dom(σ)` |
| `nested_typed` | `σ ⊢ input.k.s : τ`                 | `σ(k)=object fs`, `fs(s)=τ` |
| `nested_any` | `σ ⊢ input.k.s : any_`                 | otherwise |
| `cmp_same`   | `σ ⊢ e₁ op e₂ : scalar bool`          | `σ⊢e₁:τ`, `σ⊢e₂:τ`, op compatible |
| `cmp_any_left` | `σ ⊢ e₁ op e₂ : scalar bool`        | `σ⊢e₁:any_` |
| `cmp_any_right` | `σ ⊢ e₁ op e₂ : scalar bool`       | `σ⊢e₂:any_` |
| `in_set`     | `σ ⊢ e in {vs} : scalar bool`          | `σ⊢e:τ`, vs non-empty |
| `in_arr`     | `σ ⊢ key[_]==e : scalar bool`          | `σ(key)=array τ`, `σ⊢e:τ` |
| `and_`       | `σ ⊢ e₁∧e₂ : scalar bool`             | both sides bool |
| `or_`        | `σ ⊢ e₁∨e₂ : scalar bool`             | both sides bool |
| `not_`       | `σ ⊢ not e : scalar bool`              | `σ⊢e:scalar bool` |

### 3.4 Evaluator Semantics

The small evaluator (`Eval.lean`) returns `Option Bool`:
- `some true` = rule fires
- `some false` = rule does not fire
- `none` = expression is undefined (attribute missing, type mismatch, etc.)

**Key semantic choice**: `not e = none` when `eval e = none` (strict
undefined propagation). OPA implements **negation-as-failure** (NAF)
where `not e = true` when `e` is undefined. This gap is Bug 1 below.



## 4. Mapping to OPA's Reference Type Checker

OPA's internal type checker (`ast/check.go`) annotates Rego modules with
type information under a schema. Our `HasType` relation captures the same
structure:

| OPA type checker concept | Lean bridge equivalent |
|--------------------------|------------------------|
| `types.A` (any)          | `RegoType.any_` |
| `types.B` (boolean)      | `RegoType.scalar .bool` |
| `types.N` (number)       | `RegoType.scalar .number` |
| `types.S` (string)       | `RegoType.scalar .string` |
| `types.Null`             | `RegoType.scalar .null` |
| `types.Array`            | `RegoType.array` |
| `types.Set`              | `RegoType.set_` |
| `types.Object`           | `RegoType.object` |
| `schema["input"]`        | `Schema` (our fixed schema) |
| `rego_type_error`        | derivation failure in `HasType` |

OPA's type checker runs `opa check --schema <schema.json>`. Our
`hasTypeDec` decision procedure mirrors this: it returns `true` iff
`HasType σ e τ` is derivable via the conservative subset of rules that
match OPA's static checker output.



## 5. Pipeline Architecture

```
rego-full/MeasureRego.lean
    ↓  lake exec measure-rego
    |  (8 shapes × 10 inputs = 80 TSV rows, Lean spec decisions)
    ↓
experiments/phase_k_opa_diff/run_opa_diff.py
    |  + 4 extended bug-probe tuples (manual)
    ↓  opa eval --data <policy.rego> --input <input.json>
    |
    ↓  Compare spec_result vs opa_result
    ↓
disagreements.json  (bug report)
```

The pipeline is identical in structure to `experiments/phase_c_diff/` for Cedar:
- Lean driver emits TSV (spec decisions)
- Python runner invokes the reference implementation
- Disagreements are the bug signal



## 6. Generator Shapes

Eight well-typed Rego rule shapes (all sorry-free per `genPolicy_sound`
in `RegoFull.Soundness`):

| Num | Name | Body | Notes |
| - | - | - | - |
| 1 | `role-eq-admin` | `input.role == "admin"` | Basic equality |
| 2 | `level-gt-3` | `input.level > 3` | Ordered number comparison |
| 3 | `role-in-set` | `input.role in {"admin","editor"}` | Set membership |
| 4 | `active-is-true` | `input.active == true` | Boolean field |
| 5 | `role-admin-and-level-gt-3` | shape 1 ∧ shape 2 | Conjunction |
| 6 | `groups-contains-ops` | `input.groups[_] == "ops"` | Array membership |
| 7 | `not-active-and-role-viewer` | `not(active==true) ∧ role=="viewer"` | Negation |
| 8 | `user-role-eq-admin` | `input.user.role == "admin"` | Nested access |



## 7. Soundness Theorem

```lean
theorem genPolicy_sound :
    ∀ (shape : PolicyShape),
      shape ∈ genPolicy.val →
      HasType fixedSchema shape.body (.scalar .bool)
```

Proved in `rego-full/RegoFull/Soundness.lean`. **Zero sorrys.** Each
shape's body has an explicit `HasType` derivation assembled from the
constructors in §3.3. The schema lookup facts are proved by kernel
reduction (`simp [fixedSchema, Schema.lookup]`).



## 8. Bugs Found

### Bug 1: Negation-as-Failure (NAF) Semantics Gap

**Classification:** Spec-vs-implementation semantic divergence  
**Severity:** Real (affects security policy evaluation)  
**Reproducer:** `experiments/phase_k_opa_diff/reproducers/bug1_naf_not_undefined.sh`

**Policy:**
```rego
package kairos
allow if {
    not (input.active == true)
    input.role == "viewer"
}
```

**Input:** `{"role": "viewer"}` (field `active` is **missing**)

| Oracle | Result |
|--------|--------|
| Lean spec | `undefined` |
| OPA v1.15.2 | `true` (ALLOW) |

**Root cause:** OPA implements **negation-as-failure** (NAF), the standard
Prolog/Datalog semantics: `not E` evaluates to `true` when `E` is undefined.
Our Lean evaluator uses strict undefined propagation: `not undefined = undefined`.

OPA's documentation states: "Negation of undefined is not the same as
negation of false." This means that when `input.active` is missing,
`(input.active == true)` is undefined, and `not (input.active == true)` is
**true** in OPA. A policy author who expects `not <missing-field>` to be
undefined (and thus fail-closed) is surprised: the policy grants access
even when the required field is absent.

**Spec source:** OPA docs, Policy Language §Negation.
The specification implicitly requires NAF, but the interaction with
missing attributes as undefined values is underspecified in OPA's
language reference. This is a real attack surface for Kubernetes admission
controller policies where `input.request.object.metadata.annotations.*` can
be absent.



### Bug 2: Polymorphic `[_]` Iteration (Array vs Object)

**Classification:** Type-safety gap: `[_]` is polymorphic, not array-typed  
**Severity:** Real (type checker does not catch this under schema)  
**Reproducer:** `experiments/phase_k_opa_diff/reproducers/bug2_in_arr_object_iteration.sh`

**Policy:**
```rego
package kairos
allow if {
    input.groups[_] == "ops"
}
```

**Input:** `{"groups": {"team1": "ops", "team2": "dev"}}` (groups is an **object**, not array)

| Oracle | Result |
|--------|--------|
| Lean spec | `undefined` (groups not an array) |
| OPA v1.15.2 | `true` (ALLOW) |

**Root cause:** OPA's `[_]` reference operator is **polymorphic**: it
iterates indices/values of arrays, keys/values of objects, and elements of
sets. Our Lean `in_arr` rule models only array semantics (consistent with
what OPA's type checker claims when a field is declared `array<string>` in
the schema). When the field holds a different type at runtime, our spec says
undefined but OPA silently iterates the object values.

**Spec-attribution:** OPA docs §References: "Iterating over objects with
`[_]`". The type checker (under schema) would flag this with `rego_type_error`
only if the schema declares `groups` as an array and the runtime value is
an object. Without a schema, `[_]` accepts any composite value. This gap
represents an implicit widening that bypasses the type system.



## 9. Future Work

- **Close NAF gap:** Extend `Eval.lean` to implement Prolog-style NAF (`not undefined = true`),
  then re-prove soundness (the soundness theorem statement changes: `not_` soundness
  requires a case split on whether the subexpression is defined).

- **Polymorphic `[_]`:** Extend `in_arr` to accept `object` and `set_` types
  alongside `array`. The `HasType` rule `in_arr` would gain an `or` in its
  premise: `σ(key) = array τ ∨ σ(key) = object τ ∨ σ(key) = set_ τ`.

- **Comprehension subset:** Array/set comprehensions are the next-highest
  priority constructor class.

- **HCL Sentinel fallback:** If further Rego mechanisation proves too costly,
  HashiCorp Sentinel is an alternative authorisation DSL with simpler grammar.
