# Canonical Reproducer  - Decimal Leading-`+` Sign Disagreement

**Discovered:** 2026-04-25 by widened bug-hunt harness.

**Severity:** evaluator_disagreement (decision-flipping). Paper-grade.

## Versions

- `cedar-policy-cli` **4.10.0** (Rust reference, in container
  `ghcr.io/athanor-ai/kairos-cedar:latest`, image hash `d9c9ceb6be83`)
- `cedar-go` **v1.6.0** (HEAD `a9a4b1b` on submodule
  `kairos-cedar/cedar-go`)
- Lean **4.29.1**

## Schema

```cedar
entity User in [Group];
entity Group;
entity Document in [Document];
entity Photo;

action view, edit, admin appliesTo {
    principal: User,
    resource: [Document, Photo],
};
```

## Request

| field | value |
|---|---|
| principal | `User::"alice"` |
| action | `Action::"view"` |
| resource | `Document::"doc1"` |
| context | `{}` |

## Policy

```cedar
permit(principal, action, resource) when {
  principal == User::"alice" && decimal("+0.0").lessThan(decimal("0.5"))
};
```

## Verdicts

| Implementation | Decision | Rationale |
|---|---|---|
| `cedar-policy` 4.10.0 (Rust) | **Deny** | `decimal()` extension parser rejects `+0.0` ("`+0.0` is not a well-formed decimal value"). The `when` body errors → policy not satisfied → no permit policies match → default `Deny`. |
| `cedar-go` v1.6.0 | **Allow** | Go's `types.ParseDecimal` calls `strconv.ParseInt(s[0:decimalIndex], 10, 64)` on the integer part, and `ParseInt` accepts a leading `+`. So `+0.0` parses to `Decimal{0}`, which is less than `0.5`, so the body evaluates to `true` and the policy permits. |

## Lean evaluator attribution

The Cedar specification (`cedar-spec/cedar-lean/Cedar/Spec/Ext/Decimal.lean`)
defines `parseDecimal` to require a non-empty integer part with no leading
`+` sign. The Lean evaluator agrees with the Rust reference; the divergence
is a **cedar-go bug**: `types/decimal.go::ParseDecimal` delegates to
Go's `strconv.ParseInt`, which silently accepts the wider input set.

## Variant cases that share the root cause

| Policy condition | Rust verdict | Go verdict | Outcome |
|---|---|---|---|
| `decimal("+0.0").lessThan(decimal("0.5"))` | Deny (parse err) | **Allow** | **decision-flip** |
| `decimal("+1.5").lessThan(decimal("0.5"))` | Deny (parse err) | Deny (parses, evals false) | asymmetric path |
| `decimal("+1.5") == decimal("1.5")` | Deny (parse err) | **Allow** | **decision-flip** |
| `decimal("+0.0") == decimal("0.0")` | Deny (parse err) | **Allow** | **decision-flip** |

The first row is the canonical reproducer captured by the harness.
Rows 3-4 are additional decision-flips with the same root cause that
were *not* in the 206-tuple sweep (the sweep used `lessThan(decimal("0.5"))`
as its baseline body, which evaluates to false for `1.5`).

## Reproducer commands

```bash
# Rust:
./scripts/dc bash -c '
  cat > /tmp/p.cedar <<EOF
permit(principal, action, resource) when {
  principal == User::"alice" && decimal("+0.0").lessThan(decimal("0.5"))
};
EOF
  cedar authorize --policies /tmp/p.cedar \
    --entities /work/experiments/phase_c_diff/bug-hunt-2026-04-25/fixtures/entities.json \
    --schema   /work/experiments/phase_c_diff/bug-hunt-2026-04-25/fixtures/schema.cedarschema \
    --request-validation false \
    --principal '"'"'User::"alice"'"'"' \
    --action    '"'"'Action::"view"'"'"' \
    --resource  '"'"'Document::"doc1"'"'"'
'
# → Deny; "`+0.0` is not a well-formed decimal value"

# Go (via the harness in this repo):
./scripts/dc bash -c '
  cd /work/experiments/phase_c_diff/bug-hunt-2026-04-25/go_harness
  GOFLAGS="-mod=mod -buildvcs=false" go build -o /tmp/h . && \
  echo "{\"idx\":\"x\",\"principal\":\"User::alice\",\"action\":\"Action::view\",\"resource\":\"Document::doc1\",\"policy\":\"permit(principal, action, resource) when { principal == User::\\\"alice\\\" && decimal(\\\"+0.0\\\").lessThan(decimal(\\\"0.5\\\")) };\"}" \
    | /tmp/h /work/experiments/phase_c_diff/bug-hunt-2026-04-25/fixtures/entities.json
'
# → {"idx":"x","decision":"Allow"}
```

## Root cause (cedar-go)

`cedar-go/types/decimal.go::ParseDecimal`:

```go
intPart, err := strconv.ParseInt(s[0:decimalIndex], 10, 64)
```

`strconv.ParseInt` accepts an optional leading `+` or `-` sign. The Cedar
specification grammar for `decimal()` does not include the leading `+`
form. The fix would be an explicit `strings.HasPrefix(s, "+")` guard
before delegating to `strconv.ParseInt`.
