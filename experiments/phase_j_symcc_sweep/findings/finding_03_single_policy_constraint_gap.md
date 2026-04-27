# Finding 03: never-errors / always-matches / never-matches limited to exactly one policy

**Class:** encoder-gap (coverage limitation)
**Subcommands affected:** never-errors, always-matches, never-matches
**Severity:** medium; limits practical applicability for multi-policy audits

## Reproducer

Schema: `schema.cedarschema`.

Two-policy file:
```cedar
permit(principal, action, resource);
forbid(principal, action, resource);
```

Command:
```bash
cedar symcc \
  --principal-type User \
  --action 'Action::"view"' \
  --resource-type Document \
  --schema schema.cedarschema \
  never-errors --policies two_policy.cedar
```

Output:
```
Analysis failed: x Expected exactly one policy, found 2
RC: 1
```

Applies identically to `always-matches` and `never-matches`.

## Root cause

`Cedar/SymCC/Verifier.lean:43-46` (verifyEvaluate):
```lean
def verifyEvaluate (φ : Term → Term → Term) (p : Policy) (εnv : SymEnv) : Result Asserts := do
  let x := p.toExpr
  ...
```

`verifyNeverErrors`, `verifyAlwaysMatches`, `verifyNeverMatches` all call
`verifyEvaluate` with a single `Policy` argument. The CLI enforces this by
refusing multi-policy files with an error. There is no API to ask "does every
policy in this set never error?" in one invocation.

## Spec source attribution

`Cedar/SymCC/Verifier.lean:78` (verifyNeverErrors):
```lean
def verifyNeverErrors (p : Policy) (εnv : SymEnv) : Result Asserts :=
  verifyEvaluate isSome p εnv
```

The function signature requires a single `Policy` (not `Policies`). The
policy-set variants (`verifyIsAuthorized`, `verifyAlwaysAllows`, etc.) accept
`Policies` lists.

## Impact

Auditing a 20-policy set for `never-errors` requires 20 separate invocations.
There is no symbolic equivalent of "does this policy set as a whole never error?"
for the single-policy subcommands. The asymmetry between single-policy and
policy-set subcommands is undocumented.

## Classification

encoder-gap: design limitation of the verifier interface, not a CVC5 or
encoding issue.
