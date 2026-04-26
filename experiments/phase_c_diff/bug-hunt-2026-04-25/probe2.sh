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
        --principal 'User::"alice"' --action 'Action::"view"' --resource 'Document::"doc1"'
    rc=$?
    echo "STDOUT_END_RC=$rc"
    echo
}

# Re-test the leading-zero with --verbose to see why no error message
probe "ld0_01_5" 'permit(principal, action, resource) when { decimal("01.5").lessThan(decimal("0.5")) };'
probe "ld0_007"  'permit(principal, action, resource) when { decimal("007.0").lessThan(decimal("0.5")) };'
probe "exp_form" 'permit(principal, action, resource) when { decimal("1e2").lessThan(decimal("0.5")) };'
probe "two_dots" 'permit(principal, action, resource) when { decimal("1.5.0").lessThan(decimal("0.5")) };'
probe "lead_space" 'permit(principal, action, resource) when { decimal(" 1.5").lessThan(decimal("0.5")) };'
probe "trail_space" 'permit(principal, action, resource) when { decimal("1.5 ").lessThan(decimal("0.5")) };'
probe "empty_frac" 'permit(principal, action, resource) when { decimal("1.").lessThan(decimal("0.5")) };'
probe "only_frac" 'permit(principal, action, resource) when { decimal(".5").lessThan(decimal("0.5")) };'
probe "frac_plus" 'permit(principal, action, resource) when { decimal("1.+5").lessThan(decimal("0.5")) };'
probe "neg_zero_4" 'permit(principal, action, resource) when { decimal("-0.0000").lessThan(decimal("0.5")) };'
probe "ip_zone" 'permit(principal, action, resource) when { ip("fe80::1%eth0").isIpv6() };'
probe "ip_v6_v4_mapped" 'permit(principal, action, resource) when { ip("::ffff:192.0.2.1").isIpv4() };'
probe "ip_v6_v4_compat" 'permit(principal, action, resource) when { ip("::192.0.2.1").isIpv4() };'
probe "ip_uppercase" 'permit(principal, action, resource) when { ip("2001:DB8::1").isIpv6() };'
probe "ip_host_bits" 'permit(principal, action, resource) when { ip("10.0.0.5/8").isIpv4() };'
probe "ip_loopback_v4" 'permit(principal, action, resource) when { ip("127.0.0.1").isLoopback() };'
probe "ip_loopback_v6" 'permit(principal, action, resource) when { ip("::1").isLoopback() };'
probe "ip_loopback_v4_mapped" 'permit(principal, action, resource) when { ip("::ffff:127.0.0.1").isLoopback() };'
probe "datetime_basic" 'permit(principal, action, resource) when { datetime("2025-04-25T00:00:00Z") < datetime("2030-01-01T00:00:00Z") };'
probe "datetime_leap" 'permit(principal, action, resource) when { datetime("2016-12-31T23:59:60Z") < datetime("2030-01-01T00:00:00Z") };'
