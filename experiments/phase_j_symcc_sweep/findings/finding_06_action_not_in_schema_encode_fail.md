# Finding 06: Missing-action encode fail vs out-of-appliesTo principal type accepted

**Class:** encoder-gap (asymmetric schema constraint enforcement)
**Subcommands affected:** all 11 (for missing action); none (for out-of-appliesTo)
**Severity:** low; reveals asymmetry in schema constraint checking

## Reproducer

Schema:
```cedar
entity Manager;
entity Employee;
entity Report;
action approve appliesTo { principal: Manager, resource: Report };
```

Policy:
```cedar
permit(principal, action, resource);
```

Case A: action not in schema at all
```bash
cedar symcc \
  --principal-type Manager \
  --action 'Action::"delete"' \
  --resource-type Report \
  --schema schema.cedarschema \
  never-errors --policies policy.cedar
# => Analysis failed: x Failed to compile policy: action not found in schema:
#    Action::"delete"
# RC: 1
```

Case B: principal type not in action's appliesTo, but present in schema
```bash
cedar symcc \
  --principal-type Employee \
  --action 'Action::"approve"' \
  --resource-type Report \
  --schema schema.cedarschema \
  always-allows --policies policy.cedar
# => x Policy set always allows: VERIFIED
# RC: 0
```

## Root cause

The Cedar symcc encoder checks whether the action UID exists in the schema
(failing with ENCODE_FAIL if not). But it does not check whether the
principal type is valid for that action's `appliesTo`. See Finding 04 for
the full `appliesTo` analysis.

The asymmetry:
- Action presence: hard-checked, raises ENCODE_FAIL
- Principal type in appliesTo: not checked, analysis proceeds on enlarged space

## Spec source attribution

`Cedar/SymCC/Compiler.lean:255-286` (compile function). The action validation
happens during `SymEnv` construction in `Cedar/SymCC/Env.lean`, while the
principal type constraint is applied at the authorization layer, not the
symbolic environment layer.

## Classification

encoder-gap: partial schema constraint enforcement creates an asymmetric
pre-analysis check surface.
