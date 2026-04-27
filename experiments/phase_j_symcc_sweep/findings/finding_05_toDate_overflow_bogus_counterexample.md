# Finding 05: toDate overflow produces bogus always-matches counterexample

**Class:** soundness-bug (false DOES NOT HOLD result)
**Subcommands affected:** always-matches, never-errors (any query using toDate
on a datetime attribute)
**Severity:** high; symcc returns a counterexample that does not witness the
property violation

## Reproducer

Schema:
```cedar
entity User {
    created: datetime,
    updated: datetime
};
action view appliesTo {
  principal: User,
  resource: User,
};
```

Policy:
```cedar
permit(principal is User, action, resource)
when { principal.created.toDate().toTime().toMilliseconds() == 0 };
```

Property: `always-matches` -- is this always true?

Semantically this should always hold: `toDate()` strips the time component,
leaving a midnight datetime, so `toTime()` of a midnight datetime is always
0 milliseconds.

Command:
```bash
cedar symcc \
  --principal-type User \
  --action 'Action::"view"' \
  --resource-type User \
  --schema schema.cedarschema \
  always-matches --policies policy.cedar
```

Output:
```
x Policy always matches: DOES NOT HOLD
  Counterexample found:
principal: User::"", action: Action::"view", resource: User::""
context: {}
entities: [
  User::"" {
    created: (datetime("1970-01-01")).offset(duration("-9223372036854775808ms")),
    ...
  },
  Action::"view",
]
RC: 0
```

But concrete evaluation with this datetime value:
```
cedar authorize ... => DENY
error while evaluating policy: error while evaluating `toDate` extension
function: overflows when computing the date of (datetime("1970-01-01")).offset(
duration("-9223372036854775808ms"))
```

The concrete evaluator returns an error (runtime overflow) for `toDate`, not
a false result. The policy errors on this input rather than returning false, so
it is not a genuine counterexample to `toDate().toTime() == 0`.

## Root cause

`Cedar/SymCC/ExtFun.lean:154-160` (Datetime.toDate):
```lean
public def toDate (dt : Term) : Term :=
  let ms_per_day := .prim (.bitvec (Int64.toBitVec 86400000))
  let dt_val := ext.datetime.val dt
  let rem := bvsmod dt_val ms_per_day
  ifFalse (bvssubo dt_val rem) (ext.datetime.ofBitVec (bvsub dt_val rem))
```

For `dt_val = INT64_MIN = -9223372036854775808`:
- `bvsmod(INT64_MIN, 86400000) = 60424192` (positive, since `bvsmod` has sign
  of divisor)
- `bvssubo(INT64_MIN, 60424192)` = overflow flag TRUE (INT64_MIN minus a
  positive number underflows)
- `ifFalse(true, ...)` returns the error term

`Cedar/SymCC/ExtFun.lean:162-173` (Datetime.toTime):
```lean
public def toTime (dt : Term) : Term :=
  ...
  ext.duration.ofBitVec (ite (bvsle zero dt_val) (bvsrem dt_val ms_per_day)
    (ite (eq (bvsrem dt_val ms_per_day) zero) zero
      (bvadd (bvsrem dt_val ms_per_day) ms_per_day)))
```

`Compiler.lean:242`:
```lean
| .toTime, [t₁] => compileCall₁ .datetime Datetime.toTime t₁
```

`compileCall₁` uses `⊙ enc t₁` which wraps in `Some(...)` but does not
propagate the error state from `toDate`'s `ifFalse`. The SMT encoding for
`toTime(toDate(INT64_MIN))` operates on the raw datetime bit-vector value even
when `toDate` would have errored, producing a spurious non-error result that CVC5
can use as a witness.

Contrast: `toDate` uses `compileCallWithError₁` which respects the error path:
```lean
| .toDate, [t₁] => compileCallWithError₁ .datetime Datetime.toDate t₁
```

`toTime` uses `compileCall₁` (no error propagation from chained results).

## Spec source attribution

- `Cedar/SymCC/ExtFun.lean:154-173`: toDate + toTime encoding
- `Cedar/SymCC/Compiler.lean:241-242`: compileCall dispatch
- `Cedar/Spec/Ext/Datetime.lean`: concrete toDate/toTime semantics with
  overflow checking

## Classification

soundness-bug: symcc returns a DOES NOT HOLD result with a counterexample
that causes a runtime error in the concrete evaluator, not a genuine property
violation. The CE witnesses an overflow error, not a case where
`toDate().toTime() != 0`.
