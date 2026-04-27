#!/usr/bin/env bash
# Verify the never-errors property on two policies via cedar symcc + CVC5.
# Expected: policy.cedar verifies; policy_unsafe.cedar yields a counterexample.

set -euo pipefail

cd "$(dirname "$0")"

run_one() {
  local pol="$1"
  echo "  --- $pol ---"
  if /usr/local/bin/cedar symcc \
       --principal-type 'User' \
       --action 'Action::"read"' \
       --resource-type 'File' \
       --schema schema.cedarschema \
       never-errors \
       --policies "$pol" 2>&1; then
    echo "  $pol: VERIFIED"
  else
    echo "  $pol: COUNTEREXAMPLE (cedar symcc returned non-zero, see output above)"
  fi
}

run_one policy.cedar
echo
run_one policy_unsafe.cedar
