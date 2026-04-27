/-
  RegoBridge.Spec.Expr: AST for the well-typed subset of Rego used in the
  kairos-cedar OPA bridge.

  Subset selected (matching OPA's production boolean-rule core):
    - Boolean rules with attribute access + equality + inequality + membership
    - Scalar types: Bool, Number, String, Null
    - Composite types: Array, Object, Set (unordered)
    - The undefined/false distinction is preserved via the `Result` type

  This is analogous to Cedar's `permit + when` core: we fix a schema for
  `input` (analogous to Cedar's TypeEnv) and characterise expressions that
  the OPA static type checker accepts.

  Example Rego policies in scope:
    allow if { input.role == "admin" }
    allow if { input.level > 3 }
    allow if { input.role in {"admin", "editor"} }
    allow if { input.user.groups[_] == "ops" }

  Out of scope (future work):
    - Comprehensions
    - User-defined functions
    - Negation (not keyword)
    - Partial rules / incremental definitions
-/

namespace Rego.Spec

/-── Types ──────────────────────────────────────────────────────────────────-/

/-- The primitive scalar types in Rego. -/
inductive ScalarType
  | bool
  | number
  | string
  | null
  deriving DecidableEq, Repr

/-- The composite/collection types in Rego. -/
inductive RegoType
  | scalar  : ScalarType → RegoType
  | array   : RegoType → RegoType          -- homogeneous (schema-typed)
  | set_    : RegoType → RegoType          -- homogeneous (schema-typed)
  | object  : List (String × RegoType) → RegoType   -- fixed-key object
  | any_    : RegoType                     -- dynamic (schema-free) type
  deriving Repr

/-- A "tag" for RegoType that strips object-field details.
    Sufficient for the kind-level comparison used in `hasTypeDec`. -/
inductive RegoTypeTag
  | scalar : ScalarType → RegoTypeTag
  | array  : RegoTypeTag → RegoTypeTag
  | set_   : RegoTypeTag → RegoTypeTag
  | object : RegoTypeTag           -- object equality is schema-name-based
  | any_   : RegoTypeTag
  deriving DecidableEq, Repr

/-- Extract the tag from a RegoType. -/
def RegoType.tag : RegoType → RegoTypeTag
  | .scalar s  => .scalar s
  | .array t   => .array t.tag
  | .set_ t    => .set_ t.tag
  | .object _  => .object
  | .any_      => .any_

/-- Structural equality on `RegoType` via tag comparison.
    For `object` types, we compare by identity (both are `.object`) which
    is sufficient for the type-checker: we only need to know if two schema
    entries have the same "shape class". -/
instance : BEq RegoType where
  beq a b := (a.tag == b.tag)

/-── Schema ─────────────────────────────────────────────────────────────────-/

/-- A schema is a mapping from `input` field names to their declared types.
    Analogous to Cedar's TypeEnv for the request type. -/
abbrev Schema := List (String × RegoType)

/-- Look up a top-level field in the schema. Returns `none` if not declared
    (the field has `any_` type in schema-free mode). -/
def Schema.lookup (s : Schema) (key : String) : Option RegoType :=
  (s.find? (fun (k, _) => k == key)).map (·.2)

/-── Expressions ────────────────────────────────────────────────────────────-/

/-- A Rego scalar literal. -/
inductive Literal
  | bool   : Bool   → Literal
  | number : Int    → Literal       -- integer subset (no float for now)
  | string : String → Literal
  | null   : Literal
  deriving DecidableEq, Repr

/-- Comparison operators. -/
inductive CmpOp
  | eq   -- ==
  | neq  -- !=
  | lt   -- <
  | le   -- <=
  | gt   -- >
  | ge   -- >=
  deriving DecidableEq, Repr

/-- A Rego expression over the chosen subset.

    Design notes:
    - `Expr.input_attr key` represents `input.<key>` (top-level attribute access)
    - `Expr.nested key subkey` represents `input.<key>.<subkey>` (one level of nesting)
    - `Expr.in_set e s` represents `e in { v1, v2, ... }` (set membership)
    - `Expr.in_arr e a` represents `e == a[_]` (array iteration membership)
    - `Expr.and_`/`Expr.or_` combine boolean sub-expressions
    - `Expr.not_` is Boolean negation (the `not` keyword in Rego)

    This covers the "simple boolean rules with attribute access + equality +
    inequality + membership" scope from the design spec. -/
inductive Expr
  | lit        : Literal → Expr
  | input_attr : String → Expr                  -- input.<key>
  | nested     : String → String → Expr         -- input.<key>.<subkey>
  | cmp        : CmpOp → Expr → Expr → Expr     -- e1 <op> e2
  | in_set     : Expr → List Literal → Expr     -- e in {v1,...}
  | in_arr     : String → Expr → Expr           -- input.<key>[_] == e  (membership)
  | and_       : Expr → Expr → Expr             -- e1, e2  (conjunction)
  | or_        : Expr → Expr → Expr             -- e1; e2  (disjunction)
  | not_       : Expr → Expr                    -- not e
  deriving Repr

/-── Typing relation ────────────────────────────────────────────────────────-/

/-- `HasType σ e τ` holds when expression `e` is well-typed at type `τ`
    under schema `σ`.

    Typing rules:

    LIT-BOOL:   ⊢ lit (bool b) : scalar bool
    LIT-NUM:    ⊢ lit (number n) : scalar number
    LIT-STR:    ⊢ lit (string s) : scalar string
    LIT-NULL:   ⊢ lit null : scalar null

    ATTR:       σ(key) = τ   ⊢ input_attr key : τ
    ATTR-ANY:   key ∉ dom(σ) ⊢ input_attr key : any_

    NESTED:     σ(key) = object fs, fs(sub) = τ   ⊢ nested key sub : τ
    NESTED-ANY: otherwise                          ⊢ nested key sub : any_

    CMP-EQ:     σ ⊢ e1 : τ   σ ⊢ e2 : τ   ⊢ cmp eq e1 e2 : scalar bool
    CMP-NEQ:    same
    CMP-ORD:    σ ⊢ e1 : scalar number   σ ⊢ e2 : scalar number
                ⊢ cmp {lt,le,gt,ge} e1 e2 : scalar bool
    CMP-ANY:    either side is any_
                ⊢ cmp op e1 e2 : scalar bool

    IN-SET:     σ ⊢ e : τ   τ matches lit type
                ⊢ in_set e vs : scalar bool

    IN-ARR:     σ(key) = array τ   σ ⊢ e2 : τ
                ⊢ in_arr key e2 : scalar bool

    AND/OR:     σ ⊢ e1 : scalar bool   σ ⊢ e2 : scalar bool
                ⊢ and_ e1 e2 : scalar bool
                ⊢ or_  e1 e2 : scalar bool

    NOT:        σ ⊢ e : scalar bool
                ⊢ not_ e : scalar bool
-/
inductive HasType : Schema → Expr → RegoType → Prop where
  -- Literals
  | lit_bool   : ∀ σ b,     HasType σ (.lit (.bool b))   (.scalar .bool)
  | lit_number : ∀ σ n,     HasType σ (.lit (.number n))  (.scalar .number)
  | lit_string : ∀ σ s,     HasType σ (.lit (.string s))  (.scalar .string)
  | lit_null   : ∀ σ,       HasType σ (.lit .null)         (.scalar .null)

  -- Attribute access: schema-declared field
  | attr_typed : ∀ σ key τ,
      σ.lookup key = some τ →
      HasType σ (.input_attr key) τ

  -- Attribute access: undeclared field (any_ type)
  | attr_any : ∀ σ key,
      σ.lookup key = none →
      HasType σ (.input_attr key) .any_

  -- Nested: input.key.subkey where key : object fs
  | nested_typed : ∀ σ key sub fs τ,
      σ.lookup key = some (.object fs) →
      (fs.find? (fun (k, _) => k == sub)).map (·.2) = some τ →
      HasType σ (.nested key sub) τ

  -- Nested: fallthrough (key not in schema, or key is not an object)
  | nested_any : ∀ σ key sub,
      (match σ.lookup key with
       | some (.object _) => False
       | _ => True) →
      HasType σ (.nested key sub) .any_

  -- Comparison: same-type operands (incl. any_ on either side)
  | cmp_same : ∀ σ op e1 e2 τ,
      (op = .eq ∨ op = .neq ∨
       (τ = .scalar .number ∧ (op = .lt ∨ op = .le ∨ op = .gt ∨ op = .ge))) →
      HasType σ e1 τ →
      HasType σ e2 τ →
      HasType σ (.cmp op e1 e2) (.scalar .bool)

  -- Comparison: any_ on left or right allows any op (dynamic dispatch)
  | cmp_any_left : ∀ σ op e1 e2,
      HasType σ e1 .any_ →
      HasType σ (.cmp op e1 e2) (.scalar .bool)

  | cmp_any_right : ∀ σ op e1 e2,
      HasType σ e2 .any_ →
      HasType σ (.cmp op e1 e2) (.scalar .bool)

  -- Set membership: expression vs literal set
  | in_set : ∀ σ e vs τ,
      HasType σ e τ →
      vs ≠ [] →
      HasType σ (.in_set e vs) (.scalar .bool)

  -- Array membership: input.key[_] == e
  | in_arr : ∀ σ key e τ,
      σ.lookup key = some (.array τ) →
      HasType σ e τ →
      HasType σ (.in_arr key e) (.scalar .bool)

  -- Conjunction (comma-separated body in Rego)
  | and_ : ∀ σ e1 e2,
      HasType σ e1 (.scalar .bool) →
      HasType σ e2 (.scalar .bool) →
      HasType σ (.and_ e1 e2) (.scalar .bool)

  -- Disjunction (semicolon-separated rules in Rego)
  | or_ : ∀ σ e1 e2,
      HasType σ e1 (.scalar .bool) →
      HasType σ e2 (.scalar .bool) →
      HasType σ (.or_ e1 e2) (.scalar .bool)

  -- Boolean negation
  | not_ : ∀ σ e,
      HasType σ e (.scalar .bool) →
      HasType σ (.not_ e) (.scalar .bool)

end Rego.Spec
