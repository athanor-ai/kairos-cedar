#!/usr/bin/env bash
# Run the six labelled requests in requests.jsonl against the policy
# set, print Allow/Deny per request alongside the expected label.
# Exits 0 if every actual decision matches its expected label.

set -euo pipefail

cd "$(dirname "$0")"

PASS=0
FAIL=0
TOTAL=0

while IFS= read -r line; do
  TOTAL=$((TOTAL + 1))
  desc=$(echo "$line" | python3 -c "import json,sys;print(json.loads(sys.stdin.read())['description'])")
  expected=$(echo "$line" | python3 -c "import json,sys;print(json.loads(sys.stdin.read())['expected'])")
  principal=$(echo "$line" | python3 -c "import json,sys;d=json.loads(sys.stdin.read())['principal'];print(d['type']+'::\"'+d['id']+'\"')")
  action=$(echo "$line" | python3 -c "import json,sys;d=json.loads(sys.stdin.read())['action'];print(d['type']+'::\"'+d['id']+'\"')")
  resource=$(echo "$line" | python3 -c "import json,sys;d=json.loads(sys.stdin.read())['resource'];print(d['type']+'::\"'+d['id']+'\"')")

  # cedar authorize returns rc=2 on Deny, rc=0 on Allow.
  # We capture stdout regardless of exit code; the rc is informational.
  decision=$(cedar authorize \
    --schema schema.cedarschema \
    --policies policy.cedar \
    --entities entities.json \
    --principal "$principal" \
    --action "$action" \
    --resource "$resource" 2>/dev/null || true)
  decision=$(echo "$decision" | grep -E '^(ALLOW|DENY)' | head -1)

  norm=$(echo "$decision" | sed 's/ALLOW/Allow/;s/DENY/Deny/')

  if [ "$norm" = "$expected" ]; then
    printf "  PASS  %-60s expected=%s actual=%s\n" "$desc" "$expected" "$norm"
    PASS=$((PASS + 1))
  else
    printf "  FAIL  %-60s expected=%s actual=%s\n" "$desc" "$expected" "$norm"
    FAIL=$((FAIL + 1))
  fi
done < requests.jsonl

echo
echo "Result: $PASS / $TOTAL passed"
exit $FAIL
