# Canonical Reproducer - cedar-go #11 (arbitrary action namespace)

**Issue:** https://github.com/cedar-policy/cedar-go/issues/11
**Title:** "cedar-go allows arbitrary entity id in Action, but aws rust implementation only supports namespace 'Action'"
**State at probe time:** open (verified 2026-04-25)

## Summary

cedar-go accepts any entity type as the `action` UID in a policy
scope-clause `==` constraint (e.g. `action == Foo::"viewAll"`). The
Rust reference (cedar-policy-core) rejects any policy whose action UID
does not have **basename `Action`** (i.e., last namespace component
must be exactly `Action`; `Foo::"viewAll"` rejected, `Foo::Action::"viewAll"`
accepted, `Action::Foo::"viewAll"` rejected).

This is a **decision-flip** in our diff-testing pipeline: a policy
that authorizes a request via `Foo::"viewAll"` is parse-error in Rust
(treated as Deny by the driver) but Allow in cedar-go.

## Versions

- `cedar-policy-cli` **4.10.0** (Rust reference)
- `cedar-go` **v1.6.0** (HEAD `a9a4b1b`)
- Lean evaluator: the cedar-spec/cedar-lean specification does **not**
  encode this restriction; `Cedar.Spec.Policy` allows the action
  scope-clause to compare against an arbitrary `EntityUID`. The
  basename-must-be-`Action` check is implemented only in Rust's
  `cst_to_ast.rs::to_action_constraint` calling
  `ActionConstraint::contains_only_action_types`. So the Lean spec
  **agrees with cedar-go's permissive behavior**.

## Inputs

### Policy with arbitrary action namespace (Rust rejects, cedar-go accepts)

```cedar
permit (
    principal,
    action == Foo::"viewAll",
    resource
);
```

### Control policy (both accept)

```cedar
permit (
    principal,
    action == Action::"view",
    resource
);
```

### Entities

```json
[
  { "uid": { "type": "User",     "id": "alice" },   "attrs": {}, "parents": [] },
  { "uid": { "type": "Document", "id": "doc1" },    "attrs": {}, "parents": [] },
  { "uid": { "type": "Foo",      "id": "viewAll" }, "attrs": {}, "parents": [] }
]
```

### Request

| field | value |
|----|----|
| principal | `User::"alice"` |
| action    | `Foo::"viewAll"` |
| resource  | `Document::"doc1"` |
| context   | `{}` |

## Verdicts

| Implementation | Decision | Detail |
|----|----|----|
| `cedar-policy` 4.10.0 (Rust) | **Deny** (parse error rc=1) | `expected an entity uid with type 'Action' but got 'Foo::"viewAll"'` |
| `cedar-go` v1.6.0            | **Allow** | Policy parses, action UID matches request, body evaluates true |
| Lean spec / `cedar-lean`     | (no parser-time check) | Spec's `ActionConstraint` permits any `EntityUID`; spec **agrees with cedar-go** |

This is a Rust-vs-Go disagreement where the **spec sides with cedar-go**.

## Reproducer commands

```bash
DIR=/work/experiments/phase_c_diff/open-issues-2026-04-25/disagreements/issue_4_action_namespace

# Rust:
./scripts/dc bash -c "cedar check-parse --policies $DIR/policy_arbitrary_action_ns.cedar"
# → rc=1, expected an entity uid with type 'Action' but got 'Foo::\"viewAll\"'

./scripts/dc bash -c "cedar authorize --policies $DIR/policy_arbitrary_action_ns.cedar \
  --entities $DIR/entities_arbitrary.json \
  --principal 'User::\"alice\"' --action 'Foo::\"viewAll\"' --resource 'Document::\"doc1\"'"
# → rc=1 (parse error)

# cedar-go:
./scripts/dc bash -c '
cd /work/experiments/phase_c_diff/open-issues-2026-04-25
ENT=disagreements/issue_4_action_namespace/entities_arbitrary.json
POL=/work/experiments/phase_c_diff/open-issues-2026-04-25/disagreements/issue_4_action_namespace/policy_arbitrary_action_ns.cedar
echo "{\"idx\":\"foo_view\",\"principal\":\"User::alice\",\"action\":\"Foo::viewAll\",\"resource\":\"Document::doc1\",\"policy_path\":\"$POL\",\"policy_format\":\"cedar\"}" \
  | ./go_harness_json/probe $ENT
'
# → {"idx":"foo_view","decision":"Allow"}
```

## Variant cases (all confirmed)

| Action UID in policy | Rust verdict | cedar-go verdict | Outcome |
|----|----|----|----|
| `Action::"view"`              | parse OK / Allow  | Allow | agreement |
| `Foo::"viewAll"`              | **parse error**   | **Allow** | **decision-flip** |
| `Foo::Action::"viewAll"`      | parse OK          | parse OK | agreement (last basename is `Action`) |
| `Action::Foo::"viewAll"`      | **parse error**   | parse OK | **decision-flip** (basename `Foo` ≠ `Action`) |

The pattern matches the cedar-go #11 commenter's observation
that cedar will operate on any namespace prefix (including unknown),
but requires that `Action` be the last element in the namespace.

## Source-line citation

### Rust (the side that's stricter than the spec)

`cedar-policy-core/src/ast/policy.rs::ActionConstraint::contains_only_action_types`
(in our pinned tree at `/work/cedar-spec/cedar/cedar-policy-core/src/ast/policy.rs:1942`)
calls `EntityUID::is_action()` which delegates to
`EntityType::is_action()` at
`/work/cedar-spec/cedar/cedar-policy-core/src/ast/entity.rs:88-99`:

```rust
pub fn is_action(&self) -> bool {
    match self {
        EntityType::EntityType(name) => {
            name.as_ref().basename() == &Id::new_unchecked_const(ACTION_ENTITY_TYPE)
        }
        ...
    }
}
```

The check is wired in at the parser layer (NotTolerant branch)
`/work/cedar-spec/cedar/cedar-policy-core/src/parser/cst_to_ast.rs:1005-1015`.

### cedar-go (the side that matches the formal spec)

cedar-go's parser at
`/work/cedar-go/internal/parser/cedar_unmarshal.go::actionScope`
parses any entity UID for the `action ==` constraint and does **not**
apply a basename check. The cedar-go AST is at
`/work/cedar-go/ast/policy.go::ActionEq` and accepts any
`types.EntityUID`. This **matches the formal spec**:
`cedar-spec/cedar-lean/Cedar/Spec/Policy.lean::ActionConstraint`
permits any `EntityUID`.

## Classification

**decision-flip (reproduced; specification-vs-implementation gap).**

This is the most paper-relevant of the four open-issue probes because:

1. It is a **clean Rust-vs-Go disagreement** that flips the
   authorization decision (Deny vs Allow).
2. The **Lean specification sides with cedar-go**, so this is
   evidence that the Rust reference implementation has a
   **specification-overstep**: it enforces an invariant
   (`action.basename() == "Action"`) that is not in the formal spec.
3. From an architectural standpoint, the bug-class is the inverse of
   what bug-hunt-2026-04-25 found for ext-types: there cedar-go is
   wider than the spec's text grammar; here cedar-go is exactly the
   spec but Rust is narrower than the spec.

## Honest reporting

- cedar-go #11 reproduces on the pinned versions.
- The "wider than spec" attribution flips compared to the
  bug-hunt-2026-04-25 ext-type findings: here **Rust is the side
  diverging from the spec**, not cedar-go. cedar-go's behavior is
  actually the more spec-faithful one for this scope-clause check.
- No new bug surfaced beyond the issue itself. (Probing variant
  forms `Foo::Action::"viewAll"` and `Action::Foo::"viewAll"`
  confirmed the basename rule but didn't surface anything new.)
