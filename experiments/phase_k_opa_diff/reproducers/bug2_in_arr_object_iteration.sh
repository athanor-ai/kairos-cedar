#!/usr/bin/env bash
# BUG-2: in_arr (array membership) works on objects too in OPA
#
# Lean spec: in_arr "groups" e evaluates by looking up "groups" as an array
#            If groups is NOT an array → undefined
# OPA:       input.groups[_] iterates over array indices OR object values
#            If groups = {"team1": "ops", "team2": "dev"}, OPA iterates values
#            and finds "ops" → ALLOW
#
# Policy: allow if { input.groups[_] == "ops" }
# Input:  {"groups": {"team1": "ops", "team2": "dev"}}  (object, not array)
#
# Lean spec says: UNDEFINED (groups is not an array)
# OPA says:       ALLOW (object[_] iterates values)
#
# This reveals a semantic gap in our `in_arr` rule which models only array iteration.
# OPA's [_] operator is polymorphic: it works on arrays (index → value) and
# objects (key → value) and even sets.
#
# Source: https://www.openpolicyagent.org/docs/latest/policy-language/#references

OPA=${OPA:-/tmp/opa}
POLICY=$(cat <<'REGO'
package kairos

allow if {
    input.groups[_] == "ops"
}
REGO
)

INPUT='{"groups": {"team1": "ops", "team2": "dev"}}'

echo "=== BUG-2: in_arr object iteration gap ==="
echo ""
echo "Policy:"
echo "$POLICY"
echo ""
echo "Input: $INPUT"
echo ""
echo "Lean spec prediction: UNDEFINED (groups is not an array in our typing relation)"
echo "OPA result:"
echo "$INPUT" | $OPA eval \
    --data <(echo "$POLICY") \
    --stdin-input \
    --format json \
    'data.kairos.allow'

echo ""
echo "Expected per Lean spec: {}"    # undefined
echo "Actual OPA result:      allow = true"
echo ""
echo "Attribution: OPA docs §References — 'The [_] operator works on arrays, objects, and sets'"
echo "Lean source: rego-full/RegoFull/Soundness.lean, shape6_wt"
echo "Spec:        opa-bridge/RegoBridge/Spec/Eval.lean, eval (.in_arr key e2) only matches .array"
