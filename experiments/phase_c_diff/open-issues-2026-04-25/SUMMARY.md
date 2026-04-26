# Open-Issues Probe Summary - 2026-04-25

Re-tested four open GitHub issues filed against cedar-policy/cedar and
cedar-policy/cedar-go on the same pinned versions used by
`bug-hunt-2026-04-25`:

- `cedar-policy-cli` **4.10.0** (Rust, container
  `ghcr.io/athanor-ai/kairos-cedar:latest`, image hash `d9c9ceb6be83`)
- `cedar-go` **v1.6.0** (HEAD `a9a4b1b1450917d5df2a3c7c17d6567035fd8fcb`)
- Lean 4.29.1 / `cedar-spec/cedar-lean`

## Per-issue outcomes

| # | Issue | Bug class as filed | Outcome on pinned versions | Adjacent finding? |
|----|----|----|----|----|
| 1 | cedar #1702 - common-type entity shape | schema-format-asymmetric | reproduced | yes - cedar-go silently drops the common-type ref on `MarshalCedar`, producing a semantically-different schema |
| 2 | cedar #1682 - `__cedar` attribute | cross-format-asymmetric | reproduced in both Rust and cedar-go (same direction; both reject Cedar text, both accept JSON) | no - both implementations inherit a spec-grammar gap |
| 3 | cedar #2116 - zero-arg method-style call | round-trip-asymmetric | reproduced in Rust | yes - cedar-go panics on `MarshalCedar` of the same JSON policy (`index out of range [0]` at `internal/parser/cedar_marshal.go:199`) |
| 4 | cedar-go #11 - arbitrary action namespace | decision-flip | reproduced | no - but the Lean spec sides with cedar-go, so the Rust reference is the spec-divergent side |

## New bugs surfaced by these probes

These were **not** in the original four issues; they were observed
while constructing the reproducers and are paper-relevant on their own.

### NEW-1 · cedar-go schema marshaller drops common-type entity shape

- Surfaced by: probing #1702.
- Reproduced at: `disagreements/issue_1_common_type_entity_shape/` via `go_roundtrip/probe`.
- Failure mode: `Schema.UnmarshalJSON({Baz.shape := commonType "Foo"})` succeeds, `Schema.MarshalCedar()` succeeds, but the marshalled Cedar text is **semantically different** - emits `entity Baz {}` (empty record) instead of erroring like Rust's `cedar translate-schema --direction json-to-cedar` does ("entity shapes may not reference common type definitions"). The marshalled schema, when re-parsed, produces a schema where `Baz::"x".bar` is undeclared, while the original JSON schema has `Baz::"x".bar : Long`.
- Severity: medium-to-high. Would manifest as silent type-check drift in policies that reference attributes through a common-type shape after a schema round-trip through cedar-go.
- Source: cedar-go `x/exp/schema/internal/parser` - the schema AST walker has no case for the common-type-reference-as-shape variant.

### NEW-2 · cedar-go panics on `MarshalCedar` of zero-arg method-style call

- Surfaced by: probing #2116.
- Reproduced at: `disagreements/issue_3_offset_zero_arg/go_marshalcedar/`.
- Failure mode: `Policy.UnmarshalJSON({"offset":[]})` succeeds; `Policy.MarshalCedar()` then **panics** with `runtime error: index out of range [0] with length 0` at `cedar-go/internal/parser/cedar_marshal.go:199` (the `IsMethod`-branch reads `n.Args[0]` without a length check).
- Severity: high. An attacker-controlled JSON policy crashes the cedar-go marshaller. Compare to Rust's path which emits invalid-but-non-panicky `offset()`.
- Source: `cedar-go/internal/parser/cedar_marshal.go:199` - `marshalChildNode(n.precedenceLevel(), n.Args[0], buf)` inside `if info.IsMethod`.

## Architectural-pattern story (matches bug-hunt-2026-04-25)

The bug-hunt-2026-04-25 evidence was that cedar-go's ext-type parsers
(decimal, ip) **delegate to Go stdlib** that accepts a superset of the
Cedar spec's grammar - so cedar-go ends up wider than the spec.

The four open-issue probes land in three distinct buckets relative to
that pattern:

- Issue #1702 / NEW-1: cedar-go's *schema marshaller* is wider than the Rust schema marshaller - it accepts inputs the Rust side honestly errors on. Same architectural shape (cedar-go too permissive), different code path (schema marshalling rather than ext-type parsing).
- Issue #1682: same in both implementations - the cross-format asymmetry is a **spec-grammar gap** (Cedar-text grammar < JSON grammar on reserved-identifier handling). Not a Rust-vs-Go disagreement.
- Issue #2116 / NEW-2: same root cause as #1682 (JSON-grammar is wider than Cedar-text-grammar on call-arity), but cedar-go's failure mode is qualitatively worse than Rust's (panic vs invalid output).
- Issue cedar-go #11: **inverse** pattern. Here cedar-go matches the formal Lean spec, and the Rust reference enforces an extra invariant (`action.basename() == "Action"`) that is not in the spec. So this is **Rust wider-than-spec on enforcement** / **narrower-than-spec on accepted inputs**.

## Honest reporting

- All four reported behaviors **do** still reproduce on the pinned versions. None of the four issues is fixed-upstream-but-still-open on this snapshot.
- We **did not** independently verify the upstream-fix status for later cedar-go / cedar releases; these probes are scoped to the pinned bug-hunt versions.
- We do not claim cedar-go #11 as a "cedar-go bug" without the spec caveat - the Lean spec actually sides with cedar-go, so this is a spec-vs-impl gap on the Rust side. The `wider-than-spec` framing in the paper should distinguish these directions.

## Files

- `disagreements/issue_1_common_type_entity_shape/` - schema files + cedar-go `MarshalCedar` round-trip probe
- `disagreements/issue_2_cedar_attribute_keyword/` - schema, two policy formats, entities
- `disagreements/issue_3_offset_zero_arg/` - JSON policy + cedar-go `MarshalCedar` panic probe
- `disagreements/issue_4_action_namespace/` - two policy variants + entities
- `go_harness/` - copy of the bug-hunt Cedar-text driver
- `go_harness_json/` - extended driver that also accepts JSON-format policies (single-policy form for cedar-go) and parses namespaced entity-UID args by splitting on the **last** `::`
- `fixtures/` - copy of the bug-hunt-2026-04-25 schema + entities
