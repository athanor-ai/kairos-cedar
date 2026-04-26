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
        --principal 'User::"alice"' --action 'Action::"view"' --resource 'Document::"doc1"' \
        --verbose 2>&1
    rc=$?
    echo "STDOUT_END_RC=$rc"
    echo
}

# unwrap the && so we see the parse outcome on its own
probe "isolate_01_5" 'permit(principal, action, resource) when { decimal("01.5") == decimal("01.5") };'
probe "isolate_01_5_v2" 'permit(principal, action, resource) when { decimal("01.5") == decimal("1.5") };'
probe "isolate_007"  'permit(principal, action, resource) when { decimal("007.0") == decimal("7.0") };'

# pure parse; true if parse succeeds & equality works
probe "and_decimal" 'permit(principal, action, resource) when { decimal("01.5") == decimal("01.5") && true };'

# put decimal under unless { } to invert
probe "unless_01_5" 'permit(principal, action, resource) unless { decimal("01.5").lessThan(decimal("0.5")) };'
