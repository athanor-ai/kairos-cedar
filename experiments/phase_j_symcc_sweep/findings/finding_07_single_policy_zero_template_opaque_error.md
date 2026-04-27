# Finding 07: Template-slot policies yield opaque "found 0" error in single-policy subcommands

**Class:** encoder-gap (unhelpful error message for template policies)
**Subcommands affected:** never-errors, always-matches, never-matches,
matches-equivalent, matches-implies, matches-disjoint
**Severity:** low; poor diagnostics, not a soundness issue

## Reproducer

Template policy:
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
  never-errors --policies template.cedar
```

Output:
```
Analysis failed: x Expected exactly one policy, found 0
RC: 1
```

No mention that the policy file contained a template. The user sees "found 0"
and has no indication that the template was silently dropped before the count
was checked.

For matches-equivalent:
```bash
cedar symcc ... matches-equivalent \
  --policy1 template.cedar --policy2 template.cedar
# => Analysis failed: x Expected exactly one policy in --policy1, found 0
```

## Root cause

The Cedar CLI pre-processing strips template policies from the policy set before
passing it to `cedar symcc`. For single-policy subcommands, the stripped set
has zero policies, triggering the "Expected exactly one policy, found 0" error.
The warning "policy set contains N template(s), which will be ignored by
analysis" is NOT emitted for single-policy subcommands (only for policy-set
subcommands).

## Spec source attribution

The CLI-level handling in the cedar binary (not in cedar-spec Lean source).
The Lean verifier types require `Policy` (not template), so the CLI must
strip templates before dispatch.

## Classification

encoder-gap: the diagnostic path for single-policy subcommands does not
surface the template-drop reason for the "found 0" count.
