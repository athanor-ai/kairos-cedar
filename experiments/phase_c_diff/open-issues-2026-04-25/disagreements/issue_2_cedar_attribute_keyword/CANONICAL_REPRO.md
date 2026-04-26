# Canonical Reproducer - cedar #1682 (`__cedar` attribute, format-asymmetric)

**Issue:** https://github.com/cedar-policy/cedar/issues/1682
**Title:** "Record attribute identifiers" (Cedar text policy can't reference attribute named `__cedar`; JSON policy can)
**State at probe time:** open (verified 2026-04-25)

## Summary

The reporter notes that an entity attribute named `__cedar` can be
declared in a schema and referenced from a *JSON-format* policy, but the
*Cedar-text-format* policy parser refuses the same reference because it
treats anything containing `__cedar` as a reserved identifier. This is a
**cross-format asymmetry inside one implementation** rather than a
Rust-vs-Go disagreement. The probe confirms the asymmetry **on both**
the cedar-policy 4.10.0 reference and cedar-go v1.6.0 - i.e. cedar-go
inherits the same asymmetry from upstream.

## Versions

- `cedar-policy-cli` **4.10.0** (Rust reference, container
  `ghcr.io/athanor-ai/kairos-cedar:latest`, image hash `d9c9ceb6be83`)
- `cedar-go` **v1.6.0** (HEAD `a9a4b1b`)
- Lean evaluator: applies only after parsing; the bug is in Cedar-text
  parsing so Lean does not reach the evaluator. **Lean attribution:
  consistent with Rust** because the Lean spec's `parseExpr` (which the
  Rust grammar mirrors) likewise rejects `__cedar` identifiers.

## Inputs

### Schema (Cedar text)

```cedar
namespace FS {
    entity Disk = {
        "__cedar": Bool
    };
    entity Person;
}

action Write appliesTo {
    principal: FS::Person,
    resource: [FS::Disk],
};
```

### Cedar-text policy (the form rejected by both implementations)

```cedar
permit ( principal, action, resource is FS::Disk )
when { resource.__cedar };
```

### JSON policy (the form accepted by both implementations - single-policy form for cedar-go)

```json
{
  "effect": "permit",
  "principal": { "op": "All" },
  "action": { "op": "All" },
  "resource": { "op": "is", "entity_type": "FS::Disk" },
  "conditions": [
    {
      "kind": "when",
      "body": { ".": { "left": { "Var": "resource" }, "attr": "__cedar" } }
    }
  ]
}
```

(For Rust the same body is wrapped in the `staticPolicies` envelope at
`policy.json`. Both Rust and cedar-go accept their respective JSON
formats.)

### Entities

```json
[
  { "uid": { "type": "FS::Person", "id": "alice" }, "attrs": {}, "parents": [] },
  { "uid": { "type": "FS::Disk",   "id": "disk1" }, "attrs": { "__cedar": true }, "parents": [] }
]
```

### Request

| field | value |
|----|----|
| principal | `FS::Person::"alice"` |
| action | `Action::"Write"` |
| resource | `FS::Disk::"disk1"` |
| context | `{}` |

## Verdicts

| Implementation | Format | Decision | Detail |
|----|----|----|----|
| `cedar-policy` 4.10.0 (Rust) | Cedar text | Parse error (rc=1) | `The name __cedar contains __cedar, which is reserved` |
| `cedar-policy` 4.10.0 (Rust) | JSON       | **Allow**          | Body evaluates true on `resource.__cedar = true` |
| `cedar-go`     v1.6.0       | Cedar text | Parse error (rc=2) | `parser error: parse error at <input>:6:25 "}": expected ident` |
| `cedar-go`     v1.6.0       | JSON       | **Allow**          | Body evaluates true |

cedar-go's Cedar-text rejection has a different surface error
(`expected ident` instead of `__cedar is reserved`) but the underlying
behavior is the same: the Cedar-text grammar refuses an identifier
starting with `__` after a `.`.

## Reproducer commands

```bash
# Rust:
DIR=/work/experiments/phase_c_diff/open-issues-2026-04-25/disagreements/issue_2_cedar_attribute_keyword
./scripts/dc bash -c "
cedar authorize --policies $DIR/policy.cedar --entities $DIR/entities.json \
  --schema $DIR/schema.cedarschema --principal 'FS::Person::\"alice\"' \
  --action 'Action::\"Write\"' --resource 'FS::Disk::\"disk1\"'
# → rc=1, '__cedar contains __cedar, which is reserved'

cedar authorize --policies $DIR/policy_single.json --policy-format json \
  --entities $DIR/entities.json --schema $DIR/schema.cedarschema \
  --principal 'FS::Person::\"alice\"' \
  --action 'Action::\"Write\"' --resource 'FS::Disk::\"disk1\"'
# → ALLOW
"

# cedar-go (via go_harness_json/probe in this dir):
./scripts/dc bash -c '
cd /work/experiments/phase_c_diff/open-issues-2026-04-25
ENT=disagreements/issue_2_cedar_attribute_keyword/entities.json
echo "{\"idx\":\"j\",\"principal\":\"FS::Person::alice\",\"action\":\"Action::Write\",\"resource\":\"FS::Disk::disk1\",\"policy_path\":\"/work/experiments/phase_c_diff/open-issues-2026-04-25/disagreements/issue_2_cedar_attribute_keyword/policy_single.json\",\"policy_format\":\"json\"}" \
  | ./go_harness_json/probe $ENT
# → {"idx":"j","decision":"Allow"}
'
```

## Lean evaluator attribution

The Cedar-Lean specification at
`cedar-spec/cedar-lean/Cedar/Spec/Expr.lean` and the parsing rules in
`cedar-spec/cedar-policy/parser` treat any identifier matching the
regex `__.*__` (and bare `__cedar`) as reserved. The Lean spec
authoritatively **agrees with the Cedar-text rejection** of
`resource.__cedar`. The Lean evaluator never sees the value because
the policy can't be parsed.

For the JSON form, the Lean / EST front-end does *not* run an
identifier-reservation check on the `attr` field of the `.` node - the
attribute name is a JSON string, not a parsed identifier. The
Lean/Cedar EST therefore implicitly **agrees with the JSON-side
Allow**: it would evaluate `resource."__cedar"` (the EST attribute) and
look up the `__cedar` attribute on the entity, which is `true`.

So the Lean spec **mirrors** the cross-format asymmetry observed in
both implementations: the bug is in the spec's two grammars not being
in sync about reserved-identifier handling, not in either Rust or Go.

## Classification

**cross-format-asymmetric (reproduced; same direction in both
implementations).**

This is exactly the bug-class the FMCAD paper's diff-testing pipeline
is designed to surface: the same Cedar policy expressed in two formats
produces different decisions because the Cedar-text grammar is a
proper subset of the JSON grammar. cedar-go inherits this from
upstream rather than introducing it.

## Source-line citation (cedar-go)

Cedar-text identifier rejection: `cedar-go/internal/parser/cedar_unmarshal.go`
(reserved-keyword guard at line 195: `if !t.isIdent() && !t.isReservedKeyword()`
and the calling site for record-attribute access).

JSON path bypass: `cedar-go/internal/json/json.go::policyJSON` and
`json_unmarshal.go` - the `attr` field is unmarshalled as a plain
`json:"attr"` string with no reserved-identifier check, so the JSON
parser is **wider than the Cedar-text grammar**. This matches the
architectural pattern from the bug-hunt-2026-04-25 evidence: cedar-go's
JSON paths delegate to encoding/json and accept any string the Cedar
specification's text grammar would reject.

## Honest reporting

- `cedar` #1682 reproduces on both pinned implementations.
- It is **not** a Rust-vs-Go disagreement - both sides exhibit the
  same cross-format asymmetry, which is consistent with the spec's
  two grammars diverging on reserved-identifier handling.
- For paper purposes this is a **specification-grammar gap**
  (Cedar-text grammar < JSON grammar). It is paper-relevant under the
  "diff-testing surfaces format-asymmetric specs" framing rather than
  "diff-testing surfaces ref vs alternate disagreement."
