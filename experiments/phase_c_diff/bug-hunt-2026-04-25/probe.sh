#!/bin/bash
# Probe cedar CLI behavior on common edge cases to calibrate our classifier.
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

probe "ok_decimal" 'permit(principal, action, resource) when { decimal("0.1").lessThan(decimal("0.5")) };'
probe "bad_decimal_overprec" 'permit(principal, action, resource) when { decimal("0.12345").lessThan(decimal("0.5")) };'
probe "bad_decimal_no_dot" 'permit(principal, action, resource) when { decimal("1").lessThan(decimal("0.5")) };'
probe "bad_decimal_lead_zero" 'permit(principal, action, resource) when { decimal("01.5").lessThan(decimal("0.5")) };'
probe "ok_ip" 'permit(principal, action, resource) when { ip("127.0.0.1").isIpv4() };'
probe "bad_ip_invalid" 'permit(principal, action, resource) when { ip("256.0.0.1").isIpv4() };'
probe "ip_v4_lead_zero" 'permit(principal, action, resource) when { ip("127.000.000.001").isIpv4() };'
