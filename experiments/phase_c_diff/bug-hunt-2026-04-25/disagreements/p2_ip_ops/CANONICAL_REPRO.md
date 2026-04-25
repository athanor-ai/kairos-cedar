# Canonical Reproducer — IPv6 Zone-Identifier Disagreement

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
  ip("fe80::1%eth0").isIpv6()
};
```

## Verdicts

| Implementation | Decision | Rationale |
|---|---|---|
| `cedar-policy` 4.10.0 (Rust) | **Deny** | `ipaddr` parser rejects `fe80::1%eth0` ("invalid IP address"). The `when` body errors → policy not satisfied → no permit policies match → default `Deny`. |
| `cedar-go` v1.6.0 | **Allow** | Go's `netip.ParsePrefix`/`netip.ParseAddr` accept `fe80::1%eth0` (zone identifier per RFC 6874). `.isIpv6()` returns `true`. The `when` body is `true` → `Allow`. |

## Lean evaluator attribution

The Cedar specification (`cedar-spec/cedar-lean/Cedar/Spec/Ext/IPAddr.lean`)
defines an `ipaddr` grammar with no zone-identifier production. The Lean
evaluator agrees with the Rust reference; the divergence is a **cedar-go
bug**: `types/ipaddr.go::ParseIPAddr` delegates to Go's `net/netip`
which accepts RFC 6874 zone identifiers, a strict superset of the Cedar
grammar.

## Variant cases (8 zone-id policies tested)

| Policy condition | Rust | Go | Outcome |
|---|---|---|---|
| `ip("fe80::1%eth0").isIpv6()` | Deny | **Allow** | **decision-flip** |
| `ip("fe80::1%eth0").isIpv4()` | Deny (parse err) | Deny (parses, false) | asymmetric path |
| `ip("fe80::1%eth0").isLoopback()` | Deny (parse err) | Deny (parses, false) | asymmetric path |
| `ip("fe80::1%eth0").isMulticast()` | Deny (parse err) | Deny (parses, false) | asymmetric path |
| `ip("fe80::1%eth0") == ip("fe80::1%eth0")` | Deny (parse err) | **Allow** | **decision-flip** (\*) |
| `ip("fe80::1%eth0").isInRange(ip("fe80::/10"))` | Deny (parse err) | **Allow** | **decision-flip** (\*) |
| `ip("fe80::1%0").isIpv6()` | Deny (parse err) | **Allow** | **decision-flip** (\*) |
| `ip("fe80::1%1").isIpv6()` | Deny (parse err) | **Allow** | **decision-flip** (\*) |

(\*) Verified by direct probe (`probe_zone.sh` + `_probe_go_zone.jsonl`)
during widening; not in the harness 206-tuple sweep because the
`p2_ip_ops` shape only enumerates `{isIpv4,isIpv6,isLoopback,isMulticast}`.
The `isIpv6()` row is the canonical reproducer captured by the sweep.

## Reproducer commands

```bash
# Rust:
./scripts/dc bash -c '
  cat > /tmp/p.cedar <<EOF
permit(principal, action, resource) when { ip("fe80::1%eth0").isIpv6() };
EOF
  cedar authorize --policies /tmp/p.cedar \
    --entities /work/experiments/phase_c_diff/bug-hunt-2026-04-25/fixtures/entities.json \
    --schema   /work/experiments/phase_c_diff/bug-hunt-2026-04-25/fixtures/schema.cedarschema \
    --request-validation false \
    --principal '"'"'User::"alice"'"'"' \
    --action    '"'"'Action::"view"'"'"' \
    --resource  '"'"'Document::"doc1"'"'"'
'
# → Deny; "invalid IP address: fe80::1%eth0"

# Go (via the harness in this repo):
./scripts/dc bash -c '
  cd /work/experiments/phase_c_diff/bug-hunt-2026-04-25/go_harness
  GOFLAGS="-mod=mod -buildvcs=false" go build -o /tmp/h . && \
  echo "{\"idx\":\"x\",\"principal\":\"User::alice\",\"action\":\"Action::view\",\"resource\":\"Document::doc1\",\"policy\":\"permit(principal, action, resource) when { ip(\\\"fe80::1%eth0\\\").isIpv6() };\"}" \
    | /tmp/h /work/experiments/phase_c_diff/bug-hunt-2026-04-25/fixtures/entities.json
'
# → {"idx":"x","decision":"Allow"}
```

## Root cause (cedar-go)

`cedar-go/types/ipaddr.go::ParseIPAddr` calls `netip.ParsePrefix` and
falls back to `netip.ParseAddr`. Go's `net/netip` accepts zone
identifiers in IPv6 addresses (per RFC 6874 / RFC 4007). The Cedar
specification's `ipaddr` extension grammar does not include the
zone-identifier production; cedar-policy's Rust implementation rejects
`%`-suffixed addresses. The fix would be a `strings.Contains(s, "%")`
guard before delegating to `netip`, similar to the existing guard for
IPv4-embedded-in-IPv6 dotted notation.

## Why this matters for the FMCAD 2026 paper

This is exactly the kind of divergence the §8 type-directed differential
test pipeline is designed to surface. The V1 generator produced 0/10000
disagreements because its support never produces `ip()`/`decimal()`
literals. The widened harness exercises the extension-type ↔
standard-library boundary that the §Limitations section flagged as the
most-likely-drift site; one of the eight zone-id variants flips the
`Allow`/`Deny` decision (rows 1, 5, 6, 7, 8 in the variants table).
