# Finding 02: Template policies silently dropped from policy-set analysis

**Class:** encoder-gap / soundness concern
**Subcommands affected:** always-allows, always-denies, equivalent, implies,
disjoint (all policy-set subcommands)
**Severity:** High; analysis result is unsound relative to the linked-template
authorization outcome

## Reproducer

Schema: `schema.cedarschema` (fixed User/Document/Photo schema).

Template-only permit policy:
```cedar
permit(principal == ?principal, action, resource);
```

Command:
```bash
cedar symcc \
  --principal-type User \
  --action 'Action::"view"' \
  --resource-type Document \
  --schema schema.cedarschema \
  always-denies --policies template.cedar
```

Output:
```
  warning: policy set contains 1 policy template(s), which will be ignored by
  analysis

x Policy set always denies: VERIFIED
RC: 0
```

Concrete verification with the equivalent linked policy:
```bash
cedar authorize \
  --principal 'User::"alice"' \
  --action 'Action::"view"' \
  --resource 'Document::"doc1"' \
  --schema schema.cedarschema \
  --policies linked.cedar \
  --entities entities.json
# => ALLOW
```

## Root cause

The symcc analysis operates on static policy sets. Template policies have
unresolved slots (`?principal`, `?resource`). The Cedar CLI silently removes
them from the policy set passed to the symbolic compiler. The compiler then
sees an empty policy set and returns VERIFIED for `always-denies`.

This creates a gap between the analysis conclusion and the authorization outcome
that will occur once templates are linked to concrete entity UIDs.

Additionally, for the single-policy subcommands (never-errors, always-matches,
never-matches), a template-only file yields the opaque error:
```
Analysis failed: x Expected exactly one policy, found 0
RC: 1
```
with no indication that a template was silently discarded.

## Spec source attribution

`Cedar/SymCC/Verifier.lean:67-71` (verifyIsAuthorized):
```lean
def verifyIsAuthorized (φ : Term → Term → Term) (ps₁ ps₂ : Policies) (εnv : SymEnv) : Result Asserts := do
  let t₁ ← isAuthorized ps₁ εnv
  let t₂ ← isAuthorized ps₂ εnv
  let xs := (ps₁ ++ ps₂).map Policy.toExpr
  (enforce xs εnv).elts ++ [not (φ t₁ t₂)]
```

The `ps₁`/`ps₂` arguments are `Policies`, not `PolicySet` (which would include
templates). Templates are not `Policy` values after the CLI pre-processing step.

## Impact

A user who writes a template-based policy set and runs `cedar symcc
always-denies` will receive VERIFIED despite the fact that linking the template
permits access. The WARNING is emitted to stderr but the exit code is 0.

## Classification

encoder-gap with soundness concern: the verifier's conclusion is valid for the
compiled policy set (zero policies), but the compiled policy set does not
represent the full authorization semantics of the template-based set.
