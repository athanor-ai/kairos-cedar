# Canonical Reproducer — Datetime Expanded-Year Format Decision Flip (B2.3)

**Discovered:** 2026-04-25 by phase_h2_datetime_duration widened-shapes harness.

**Classification:** evaluator_disagreement (decision-flipping). Paper-grade.

**Finding ID:** B2.3 (extends the §7.4 architectural-pattern family of B2.1/B2.2)

## Versions

- `cedar-policy-cli` **4.10.0** (Rust reference, in container
  `ghcr.io/athanor-ai/kairos-cedar:latest`, image hash `d9c9ceb6be83`)
- `cedar-go` **v1.6.0** (HEAD `a9a4b1b` on submodule `kairos-cedar/cedar-go`)
- Lean **4.29.1**

## Root cause

Cedar RFC 110 introduces an ISO 8601 "expanded year" format: `(+|-)YYYYYYYYY-MM-DD[T...]`
where the year is 9 digits (signed). cedar-go v1.6.0 implements RFC 110 in `ParseDatetime`
(`cedar-go/types/datetime.go`, lines 106–125). The Rust implementation in
cedar-policy-core 4.10.0 does NOT implement RFC 110 — its `DATE_PATTERN` regex is
`r"^([0-9]{4})-([0-9]{2})-([0-9]{2})"` (exactly 4 digits, no sign prefix).
The Lean reference spec (`cedar-spec/cedar-lean/Cedar/Spec/Ext/Datetime.lean`,
`checkComponentLen`) also requires exactly 4-digit years.

Because cedar-go accepts expanded-year strings and Rust/Lean reject them, any
`permit-when` policy whose condition calls `datetime("(+|-)YYYYYYYYY-MM-...")` produces:
- cedar-go: parse succeeds → expression evaluated → **Allow** (if condition is true)
- cedar-policy: extension parse error → policy condition fails → no permit applies → **Deny**

This is a **decision-flip** for any condition that evaluates to `true` in cedar-go
(e.g., a past date comparison where the condition holds).

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

## Entities

Standard fixture (see `fixtures/entities.json`): `User::"alice"` in `Group::"users"`.

## Canonical Policy

```cedar
permit(principal, action, resource) when {
  datetime("+000000001-01-01T00:00:00Z") < datetime("2030-01-01T00:00:00Z")
};
```

## Request

| field | value |
|---|---|
| principal | `User::"alice"` |
| action | `Action::"view"` |
| resource | `Document::"doc1"` |
| context | `{}` |

## Verdicts

| Implementation | Decision | Rationale |
|---|---|---|
| `cedar-policy` 4.10.0 (Rust) | **Deny** | `datetime()` extension rejects `+000000001-01-01T00:00:00Z`: "invalid date pattern". The `when` body errors → policy not satisfied → default `Deny`. |
| `cedar-go` v1.6.0 | **Allow** | `ParseDatetime` detects leading `+`, sets `yearLength=9`, reads 9-digit year `000000001` (year 1 AD), parses successfully. The comparison `year 1 < year 2030` evaluates to `true` → permit condition satisfied → **Allow**. |
| Lean reference | (not exercised directly) | `checkComponentLen` rejects the input: `year.length` for `+000000001` is 10, not 4. Lean agrees with Rust. |

## Decision-flipping variants

All inputs of the form `(+|-)DDDDDDDDD-MM-DDT...` produce a decision-flip when the
cedar-go evaluation of the resulting comparison yields `true`. The harness found
11 decision-flipping policies:

| Policy condition | Rust | Go | Outcome |
|---|---|---|---|
| `datetime("+000000001-01-01T00:00:00Z") < datetime("2030-01-01T00:00:00Z")` | Deny | **Allow** | **decision-flip** |
| `datetime("-000000001-01-01T00:00:00Z") < datetime("2030-01-01T00:00:00Z")` | Deny | **Allow** | **decision-flip** |
| `datetime("+000002000-01-01T00:00:00Z") < datetime("2030-01-01T00:00:00Z")` | Deny | **Allow** | **decision-flip** |
| `datetime("+000002025-04-25") < datetime("2030-01-01T00:00:00Z")` | Deny | **Allow** | **decision-flip** |
| `datetime("-000000001-01-01") < datetime("2030-01-01T00:00:00Z")` | Deny | **Allow** | **decision-flip** |
| `datetime("+000000001-01-01T00:00:00Z") == datetime("+000000001-01-01T00:00:00Z")` | Deny | **Allow** | **decision-flip** |
| `datetime("-000000001-01-01T00:00:00Z") == datetime("-000000001-01-01T00:00:00Z")` | Deny | **Allow** | **decision-flip** |
| `datetime("+000002000-01-01T00:00:00Z") == datetime("+000002000-01-01T00:00:00Z")` | Deny | **Allow** | **decision-flip** |
| `datetime("+000009999-12-31T23:59:59.999Z") == datetime("+000009999-12-31T23:59:59.999Z")` | Deny | **Allow** | **decision-flip** |
| `datetime("+000002025-04-25") == datetime("+000002025-04-25")` | Deny | **Allow** | **decision-flip** |
| `datetime("-000000001-01-01") == datetime("-000000001-01-01")` | Deny | **Allow** | **decision-flip** |

One asymmetric-path-both-deny case:
- `datetime("+000009999-12-31T23:59:59Z") < datetime("2030-01-01T00:00:00Z")`: Rust errors, Go evaluates to false (year 9999 is not < year 2030). Both → Deny, but for different reasons.

## Architectural pattern

The B2.1/B2.2 pattern is: "cedar-go delegates to Go stdlib whose accepted language
is a strict superset of Cedar's grammar." The datetime case (B2.3) is architecturally
related but mechanistically different: cedar-go's hand-rolled `ParseDatetime` implements
RFC 110 expanded-year format while the Rust implementation does not (cedar-policy 4.10.0
predates or did not adopt RFC 110 for this format). The cedar-go parser is not a superset
due to stdlib delegation — it is a superset due to implementing a specification revision
(RFC 110) that the Rust implementation has not yet adopted.

In both cases, the cedar-go parser accepts strings that the cedar-policy Rust reference
rejects, causing decision-flips in `permit-when` policies. The architectural observation
from §7.4 holds: extension-type parser boundaries are where specification divergence
concentrates, irrespective of the precise mechanism (stdlib delegation vs RFC revision).

## Reproducer commands

```bash
# Rust:
docker run --rm -v $(pwd):/work ghcr.io/athanor-ai/kairos-cedar:latest bash -c '
cat > /tmp/p_b23.cedar <<EOF
permit(principal, action, resource) when {
  datetime("+000000001-01-01T00:00:00Z") < datetime("2030-01-01T00:00:00Z")
};
EOF
cedar authorize --policies /tmp/p_b23.cedar \
  --entities /work/experiments/phase_h2_datetime_duration/fixtures/entities.json \
  --schema   /work/experiments/phase_h2_datetime_duration/fixtures/schema.cedarschema \
  --request-validation false \
  --principal '"'"'User::"alice"'"'"' \
  --action    '"'"'Action::"view"'"'"' \
  --resource  '"'"'Document::"doc1"'"'"'
'
# → DENY; "invalid date pattern"

# Go (via harness):
docker run --rm -v $(pwd):/work ghcr.io/athanor-ai/kairos-cedar:latest bash -c '
cd /work/experiments/phase_h2_datetime_duration/go_harness
GOFLAGS="-mod=mod -buildvcs=false" go build -o /tmp/h2 . && \
echo "{\"idx\":\"x\",\"principal\":\"User::alice\",\"action\":\"Action::view\",\"resource\":\"Document::doc1\",\"policy\":\"permit(principal, action, resource) when { datetime(\\\"+000000001-01-01T00:00:00Z\\\") < datetime(\\\"2030-01-01T00:00:00Z\\\") };\"}" \
  | /tmp/h2 /work/experiments/phase_h2_datetime_duration/fixtures/entities.json
'
# → {"idx":"x","decision":"Allow"}
```

## cedar-go root cause (code reference)

`cedar-go/types/datetime.go`, `ParseDatetime`, lines 106–124:

```go
// Check if this is an expanded year format (starts with + or -)
yearSign := 1
yearLength := 4
yearMax := uint(9999)
if s[0] == '+' || s[0] == '-' {
    yearLength = 9
    yearMax = 999999999
    if s[0] == '-' {
        yearSign = -1
    }
    s = s[1:]
} else if !unicode.IsDigit(rune(s[0])) {
    return Datetime{}, fmt.Errorf("%w: invalid year", errDatetime)
}

absYear, s, err := parseUint(s[0:], yearLength, yearMax, "year")
```

When the input starts with `+` or `-`, `yearLength` is set to 9 (RFC 110 expanded year).
cedar-policy Rust (4.10.0) has no equivalent branch — its `DATE_PATTERN` regex anchors
to `^([0-9]{4})-`, requiring exactly 4 ASCII digits with no sign prefix.
