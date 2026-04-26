#!/bin/bash
set +e
SDIR=/work/experiments/phase_c_diff/bug-hunt-2026-04-25/fixtures
ENT=$SDIR/entities.json
SCH=$SDIR/schema.cedarschema

probe() {
    local label="$1"
    local policy="$2"
    echo "===== $label ====="
    local pf=/tmp/probe_${label}.cedar
    echo "$policy" > $pf
    cedar authorize --policies $pf \
        --entities $ENT --schema $SCH \
        --request-validation false \
        --principal 'User::"alice"' --action 'Action::"view"' --resource 'Document::"doc1"' 2>&1
    echo "rc=$?"
    echo
}

# IPv4-mapped IPv6: Rust rejects, Go also rejects (Go has explicit "we don't accept" check)
probe "v4_mapped" 'permit(principal, action, resource) when { ip("::ffff:192.0.2.1").isIpv4() };'

# Smaller string of digits — does Go still accept it? RFC says "::a.b.c.d" is valid
probe "v6_compat" 'permit(principal, action, resource) when { ip("::192.0.2.1").isIpv4() };'

# 10.0.0.5/8 — host bits set in CIDR. RFC 4632 says it's host 10.0.0.5 in a /8 network.
# Rust seems to ALLOW. Go uses netip.ParsePrefix which preserves host bits.
probe "host_bits" 'permit(principal, action, resource) when { ip("10.0.0.5/8").isInRange(ip("10.0.0.0/8")) };'

# fractional second precision
probe "dt_ms_4" 'permit(principal, action, resource) when { datetime("2025-04-25T00:00:00.1234Z") < datetime("2030-01-01T00:00:00Z") };'
probe "dt_ms_6" 'permit(principal, action, resource) when { datetime("2025-04-25T00:00:00.123456Z") < datetime("2030-01-01T00:00:00Z") };'

# leading + sign
probe "dec_plus" 'permit(principal, action, resource) when { decimal("+1.5") == decimal("1.5") };'

# decimal frac with + (Go ParseUint accepts)
probe "dec_frac_plus" 'permit(principal, action, resource) when { decimal("1.+5") == decimal("1.5") };'

# pre-epoch datetime
probe "dt_pre" 'permit(principal, action, resource) when { datetime("1969-12-31T23:59:59Z") < datetime("2030-01-01T00:00:00Z") };'

# year 1
probe "dt_year_1" 'permit(principal, action, resource) when { datetime("0001-01-01T00:00:00Z") < datetime("2030-01-01T00:00:00Z") };'

# just date
probe "dt_date_only" 'permit(principal, action, resource) when { datetime("2025-04-25") < datetime("2030-01-01T00:00:00Z") };'

# offset forms
probe "dt_p0_0" 'permit(principal, action, resource) when { datetime("2025-04-25T00:00:00+00:00") < datetime("2030-01-01T00:00:00Z") };'
probe "dt_p0000" 'permit(principal, action, resource) when { datetime("2025-04-25T00:00:00+0000") < datetime("2030-01-01T00:00:00Z") };'

# uppercase IPv6 — Rust accepts, Go ParseAddr accepts too
probe "v6_upper_eq" 'permit(principal, action, resource) when { ip("2001:DB8::1") == ip("2001:db8::1") };'
