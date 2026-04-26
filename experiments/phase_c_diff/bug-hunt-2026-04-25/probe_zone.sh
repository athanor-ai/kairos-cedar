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

# Variations of zone-id IPv6
probe "v6_zone_eth0" 'permit(principal, action, resource) when { ip("fe80::1%eth0").isIpv6() };'
probe "v6_zone_0" 'permit(principal, action, resource) when { ip("fe80::1%0").isIpv6() };'
probe "v6_zone_1" 'permit(principal, action, resource) when { ip("fe80::1%1").isIpv6() };'
probe "v6_zone_loop" 'permit(principal, action, resource) when { ip("fe80::1%eth0").isLoopback() };'
probe "v6_zone_eq" 'permit(principal, action, resource) when { ip("fe80::1%eth0") == ip("fe80::1%eth0") };'
probe "v6_no_zone" 'permit(principal, action, resource) when { ip("fe80::1").isIpv6() };'
probe "v6_zone_mc" 'permit(principal, action, resource) when { ip("fe80::1%eth0").isMulticast() };'
