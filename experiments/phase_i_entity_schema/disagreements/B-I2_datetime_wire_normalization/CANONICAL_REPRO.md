# Disagreement B-I2: cedar-go's `datetime` extension wire format normalizes milliseconds

**Date:** 2026-04-26
**Filed by:** platform agent (`phase_i_entity_schema`)
**Severity:** wire-format divergence (NOT a policy-decision divergence)

***

## Versions under test

| Impl | Version | Source |
| :- | :- | :- |
| cedar-policy (Rust) | 4.10.0 | `/work/cedar-spec/cedar` workspace pin, commit `6e0f25b` (2026-04-21) |
| cedar-go (Go) | HEAD on `main` | `/work/cedar-go`, commit `a9a4b1b` (2026-03-20) |
| Lean evaluator | n/a | spec-source-read attribution only |

## Inputs

`datetime(<lit>)` for `lit` in the set of valid datetime strings without explicit milliseconds:
`"2024-01-15T00:00:00Z"`, `"2024-01-15T12:30:45Z"`, `"2000-01-01T00:00:00Z"`, etc.

## Rust output (cedar-policy 4.10.0)

```
--- Entity Test: datetime wire normalization ---
  [bare-zulu-no-ms               ] OK: input="2024-01-15T00:00:00Z" preserved
  [bare-zulu-with-time           ] OK: input="2024-01-15T12:30:45Z" preserved
  [with-ms-already               ] OK: input="2024-01-15T00:00:00.123Z" preserved
  [midnight-utc                  ] OK: input="2000-01-01T00:00:00Z" preserved
  [max-ms                        ] OK: input="2024-06-15T23:59:59.999Z" preserved
```

Rust echoes the **original constructor argument string** verbatim: no padding,
no millisecond suffix added.

## cedar-go output

```
--- datetime ParseDatetime → String() / MarshalJSON ---
  [bare-zulu-no-ms  ] input=2024-01-15T00:00:00Z   String()=2024-01-15T00:00:00.000Z   MarshalJSON()={"__extn":{"fn":"datetime","arg":"2024-01-15T00:00:00.000Z"}}
  [bare-zulu-with-time] input=2024-01-15T12:30:45Z String()=2024-01-15T12:30:45.000Z   MarshalJSON()={"__extn":{"fn":"datetime","arg":"2024-01-15T12:30:45.000Z"}}
  [with-ms-already  ] input=2024-01-15T00:00:00.123Z String()=2024-01-15T00:00:00.123Z  (unchanged — already canonical)
  [midnight-utc     ] input=2000-01-01T00:00:00Z   String()=2000-01-01T00:00:00.000Z   MarshalJSON()={"__extn":{"fn":"datetime","arg":"2000-01-01T00:00:00.000Z"}}
  [max-ms           ] input=2024-06-15T23:59:59.999Z String()=2024-06-15T23:59:59.999Z (unchanged — already canonical)
```

cedar-go always serialises datetimes with 3-digit millisecond precision by calling
`Datetime.String()` which uses `time.Format("2006-01-02T15:04:05.000Z")`.

## Wire round-trip (cedar-go)

```
--- Entity round-trip with datetime attributes ---
  [bare-zulu-no-ms  ] DIVERGE: input="2024-01-15T00:00:00Z"   output="2024-01-15T00:00:00.000Z"  byte-equal=false
  [bare-zulu-with-time] DIVERGE: input="2024-01-15T12:30:45Z" output="2024-01-15T12:30:45.000Z"  byte-equal=false
  [with-ms-already  ] OK: input="2024-01-15T00:00:00.123Z" preserved
  [midnight-utc     ] DIVERGE: input="2000-01-01T00:00:00Z"   output="2000-01-01T00:00:00.000Z"  byte-equal=false
  [max-ms           ] OK: input="2024-06-15T23:59:59.999Z" preserved
```

Any entity JSON that was originally stored without explicit milliseconds will have its
`datetime` attribute args silently rewritten after a cedar-go round-trip.

## Policy-decision test (cedar-go)

```
  [no-ms (Rust wire form)        ] decision=allow  errors=0
  [with-.000ms (cedar-go re-emit)] decision=allow  errors=0
```

Both `"2024-01-15T00:00:00Z"` and `"2024-01-15T00:00:00.000Z"` evaluate to the
same millisecond value (`1705276800000`). Policy decisions are unaffected.

## Upstream source attribution

* **Rust** `cedar-policy-core/src/entities/json/value.rs:523-543`: JSON serialisation
  of `ExtensionValue` echoes `ev.args[0]` (the original constructor string) verbatim,
  so `datetime("2024-01-15T00:00:00Z")` serialises as `{"fn":"datetime","arg":"2024-01-15T00:00:00Z"}`.
* **cedar-go** `cedar-go/types/datetime.go:270-276`: `Datetime.String()` always formats
  using `t.Format("2006-01-02T15:04:05.000Z")` — the `.000` token always emits 3-digit
  milliseconds, even when all three digits are zero.
* **cedar-go** `cedar-go/types/datetime.go:308-315`: `MarshalJSON()` calls `d.String()`
  to construct the `arg` field, so the normalised form leaks into the wire JSON.
* **Lean spec** `Cedar/Spec/Ext/Datetime.lean:44-45`: `Datetime.val : Int64` stores
  the timestamp as milliseconds. The spec accepts all five string forms at line 132-136
  (`DateOnly`, `DateUTC`, `DateUTCWithMillis`, `DateWithOffset`, `DateWithOffsetAndMillis`)
  but does not specify which form should be preserved on serialization. The impl-level
  normalisation policy is underspecified.

## Does this affect policy decisions?

**No.** `datetime` comparison operators (`<`, `<=`, etc.) compare the underlying
`value int64` (milliseconds since epoch) in cedar-go and the equivalent `Int64` in Rust.
Both parse `"T00:00:00Z"` and `"T00:00:00.000Z"` to the same millisecond value.
Tested via `cedar.Authorize` — both entity JSON forms produce `allow` on the same policy.

## Why this is still publishable

1. **Wire-format byte-inequality.** Any persistence layer, cache, or audit-log
   diff tool that compares entity JSON blobs byte-by-byte will see Rust-emitted
   `"arg":"2024-01-15T00:00:00Z"` and cedar-go-emitted `"arg":"2024-01-15T00:00:00.000Z"`
   as distinct, even though they decode to the same Cedar value.
2. **Cross-impl audit-log mismatch.** A Rust authoriser logging
   `datetime("2024-01-15T00:00:00Z")` and a cedar-go replica logging
   `datetime("2024-01-15T00:00:00.000Z")` for the same entity will be flagged
   as drift by log-diff tooling.
3. **Same class as B0/decimal.** The datetime bug follows the exact same pattern
   as the `ip` wire bug (B0) and the `decimal` wire bug: cedar-go normalises
   the constructor-arg string, Rust preserves it. All three bugs originate from
   cedar-go's `String()` method always formatting to a canonical form and then
   using that canonical form in `MarshalJSON()`.

## Classification

**B-I2** — extension wire-format normalisation (datetime), same class as B0 (ip)
and the decimal wire bug. Extension-specific: only triggers for `datetime` values
that were originally stored without explicit milliseconds.

## Reproducer paths

* `experiments/phase_i_entity_schema/repros/entity_store_implicit_uid/{go.mod,go.sum,main.go}` — Go probe (datetime wire normalization + policy-decision test)
* `experiments/phase_i_entity_schema/repros/rust_entity_schema/{Cargo.toml,main.rs}` — Rust probe (datetime preservation)
