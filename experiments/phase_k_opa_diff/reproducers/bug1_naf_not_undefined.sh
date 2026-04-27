#!/usr/bin/env bash
# BUG-1: Negation-as-failure (NAF) semantics gap
#
# Lean spec (strict semantics): not(undefined) = undefined
# OPA (Prolog-style NAF):       not(undefined) = true
#
# Policy: allow if { not (input.active == true); input.role == "viewer" }
# Input:  {"role": "viewer"}  (active field MISSING)
#
# Lean spec says: UNDEFINED (not(undefined expr) = undefined)
# OPA says:       ALLOW (true)  ← negation-as-failure fires
#
# This demonstrates a genuine semantic gap between our conservative formalisation
# and OPA's documented NAF semantics. OPA's spec says:
#   "Negation of undefined is not the same as negation of false"
#   "not <expr> evaluates to true if <expr> is undefined"
#
# Source: https://www.openpolicyagent.org/docs/latest/policy-language/#negation

OPA=${OPA:-/tmp/opa}
POLICY=$(cat <<'REGO'
package kairos

allow if {
    not (input.active == true)
    input.role == "viewer"
}
REGO
)

INPUT='{"role": "viewer"}'  # active field is missing

echo "=== BUG-1: not(undefined) semantics gap ==="
echo ""
echo "Policy:"
echo "$POLICY"
echo ""
echo "Input: $INPUT"
echo ""
echo "Lean spec prediction: UNDEFINED"
echo "OPA result:"
echo "$POLICY" | $OPA eval \
    --data /dev/stdin \
    --format json \
    - <<< "$INPUT" 2>/dev/null || \
echo "$INPUT" | $OPA eval \
    --data <(echo "$POLICY") \
    --stdin-input \
    --format json \
    'data.kairos.allow'

echo ""
echo "Expected per Lean spec: {}"   # empty = undefined
echo "Actual OPA result:      {\"result\":[{\"expressions\":[{\"value\":true,...}]}]}"
echo ""
echo "Attribution: OPA docs §Negation — 'not <expr> evaluates to true when <expr> is undefined'"
echo "Lean source: rego-full/RegoFull/Soundness.lean, shape7_wt"
echo "Spec:        opa-bridge/RegoBridge/Spec/Eval.lean, eval (.not_ e) = none when eval e = none"
