# Finding 04: appliesTo principal/resource constraints not enforced by symcc

**Class:** encoder-gap (schema constraint not modeled in SMT environment)
**Subcommands affected:** all 11
**Severity:** medium; symcc proves properties over a strictly larger request
space than concrete Cedar authorization

## Reproducer

Schema with strict appliesTo:
```cedar
entity Manager;
entity Employee;
entity Report;
action approve appliesTo {
  principal: Manager,
  resource: Report,
};
```

Policy:
```cedar
permit(principal, action, resource);
```

Command:
```bash
cedar symcc \
  --principal-type Employee \
  --action 'Action::"approve"' \
  --resource-type Report \
  --schema schema.cedarschema \
  always-allows --policies permit_any.cedar
```

Output:
```
x Policy set always allows: VERIFIED
RC: 0
```

Concrete evaluation with schema:
```bash
cedar authorize \
  --principal 'Employee::"emp1"' \
  --action 'Action::"approve"' \
  --resource 'Report::"rpt1"' \
  --schema schema.cedarschema \
  ...
# => error: principal type `Employee` is not valid for `Action::"approve"`
```

## Root cause

`Cedar/SymCC/Compiler.lean:52-57` (compileVar):
```lean
def compileVar (v : Var) (req : SymRequest) : Result Term :=
  match v with
  | .principal => if req.principal.typeOf.isEntityType then ⊙req.principal else .error .typeError
  | .action    => if req.action.typeOf.isEntityType then ⊙req.action else .error .typeError
  | .resource  => if req.resource.typeOf.isEntityType then ⊙req.resource else .error .typeError
  | .context   => if req.context.typeOf.isRecordType then ⊙req.context else .error .typeError
```

The symbolic environment models the principal/action/resource types but does not
encode the `appliesTo` constraint that limits which (principal-type, action)
combinations are valid. The concrete Cedar authorization layer rejects requests
where the principal type is not in the action's `appliesTo` principal set.

`Cedar/SymCC/Env.lean` builds the `SymEnv` from the schema, but the
`SymRequest` does not incorporate the `appliesTo` restriction.

## Spec source attribution

`Cedar/Spec/Authorizer.lean` checks request validity against the schema before
evaluating policies. The symbolic verifier does not replicate this check:
`Cedar/SymCC/Verifier.lean:67-71` uses `isAuthorized` which calls into the
policy evaluation term without a schema-level request validity gate.

## Impact

Properties verified by symcc hold over ALL well-typed requests (principal-type X,
action A, resource-type Y), even if the schema's `appliesTo` would make (X, A, Y)
an invalid request that the concrete evaluator would reject. Verification results
may be overly conservative (more SAT witnesses exist than in practice) but not
unsound for the verification direction.

For `always-allows` with an out-of-appliesTo principal type:
- symcc returns VERIFIED (because the symbolic permit-any policy holds)
- Concrete Cedar rejects the request before evaluating policies

This means `always-allows` is VERIFIED in a request space that includes invalid
requests, which is a coverage gap: the verified population is not the actual
authorization population.

## Classification

encoder-gap: the symbolic environment does not model `appliesTo` constraints.
