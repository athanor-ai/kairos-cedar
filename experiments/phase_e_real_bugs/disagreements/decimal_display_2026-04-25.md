# Disagreement: `decimal` extension wire/Display divergence

**Date:** 2026-04-25
**Filed by:** platform agent (`phase_e_real_bugs`)
**Severity:** wire-format divergence (NOT a policy-decision divergence)

---

## Versions under test

| Impl | Version | Source |
| --- | --- | --- |
| cedar-policy (Rust) | 4.10.0 | `/work/cedar-spec/cedar` workspace pin, commit `6e0f25b` (2026-04-21) |
| cedar-go (Go) | HEAD on `main` | `/work/cedar-go`, commit `a9a4b1b` (2026-03-20) |
| Lean evaluator | n/a | **not yet wired into this repro**; phase_c_diff harness compares Rust CLI ↔ Go only |

## Inputs

`decimal(<lit>)` for `lit ∈ {"1.2300", "0.0010", "-0.1000", "12.3400", "5.0000", "1.23"}`.

## Rust output (cedar-policy 4.10.0)

`EvalResult::ExtensionValue` after evaluating `decimal("<lit>")` (verbatim from `decimal_repro/rust/main.rs`):

```
1.2300                 input=1.2300        EvalResult::Display="decimal(\"1.2300\")"
0.0010                 input=0.0010        EvalResult::Display="decimal(\"0.0010\")"
-0.1000                input=-0.1000       EvalResult::Display="decimal(\"-0.1000\")"
12.3400                input=12.3400       EvalResult::Display="decimal(\"12.3400\")"
5.0000                 input=5.0000        EvalResult::Display="decimal(\"5.0000\")"
1.23                   input=1.23          EvalResult::Display="decimal(\"1.23\")"
```

Entity-store JSON round-trip (`Entities::from_json_str` → `to_json_value`):

```
round-trip     1.2300: ...{"__extn":{"fn":"decimal","arg":"1.2300"}}...
round-trip     0.0010: ...{"__extn":{"fn":"decimal","arg":"0.0010"}}...
round-trip    -0.1000: ...{"__extn":{"fn":"decimal","arg":"-0.1000"}}...
round-trip    12.3400: ...{"__extn":{"fn":"decimal","arg":"12.3400"}}...
round-trip     5.0000: ...{"__extn":{"fn":"decimal","arg":"5.0000"}}...
round-trip       1.23: ...{"__extn":{"fn":"decimal","arg":"1.23"}}...
```

Rust echoes the **original constructor argument string** — no padding, no trim.

## Go output (cedar-go a9a4b1b)

```
trailing-zeros   input="1.2300"   String()="1.23"      MarshalJSON()={"__extn":{"fn":"decimal","arg":"1.23"}}
smallest-frac    input="0.0010"   String()="0.001"     MarshalJSON()={"__extn":{"fn":"decimal","arg":"0.001"}}
negative         input="-0.1000"  String()="-0.1"      MarshalJSON()={"__extn":{"fn":"decimal","arg":"-0.1"}}
all-four         input="12.3400"  String()="12.34"     MarshalJSON()={"__extn":{"fn":"decimal","arg":"12.34"}}
int-with-zeros   input="5.0000"   String()="5.0"       MarshalJSON()={"__extn":{"fn":"decimal","arg":"5.0"}}
already-canonical input="1.23"    String()="1.23"      MarshalJSON()={"__extn":{"fn":"decimal","arg":"1.23"}}
```

Go canonicalises by formatting the i64 raw value (`12300`) with `fmt.Sprintf("%d.%04d", ...)`
then trims **up to three** trailing zeros. Note `5.0000 → "5.0"` (only one zero kept because
the trim cap is 3) — this is itself a peculiarity worth flagging.

## Wire round-trip (cedar-go)

Replaying Rust-emitted wire bytes through `json.Unmarshal` + `MarshalJSON`:

```
in={"__extn":{"fn":"decimal","arg":"1.2300"}}   out={"__extn":{"fn":"decimal","arg":"1.23"}}    byte-equal=false
in={"__extn":{"fn":"decimal","arg":"0.0010"}}   out={"__extn":{"fn":"decimal","arg":"0.001"}}   byte-equal=false
in={"__extn":{"fn":"decimal","arg":"-0.1000"}}  out={"__extn":{"fn":"decimal","arg":"-0.1"}}    byte-equal=false
in={"__extn":{"fn":"decimal","arg":"1.23"}}     out={"__extn":{"fn":"decimal","arg":"1.23"}}    byte-equal=true
```

## Upstream source attribution

* **Rust** `cedar-policy-core/src/extensions/decimal.rs:164-172` — `Display` always
  prints `{}.{:04}` (4 fractional digits, no trim). Verified at the workspace pin.
* **Rust** `cedar-policy-core/src/extensions/decimal.rs:175-191` — `canonical_repr()`
  returns the `Display` form (used by TPE/normalisation, *not* by the standard evaluator
  output path).
* **Rust** `cedar-policy-core/src/entities/json/value.rs:523-543` — JSON serialisation
  of `ExtensionValue` echoes the constructor's original args, so `decimal("1.2300")` →
  `{"fn":"decimal","arg":"1.2300"}`. The `Display`/`canonical_repr` output is **not**
  used here.
* **Go** `cedar-go/types/decimal.go:143-162` — `String()` always normalises via
  `%d.%04d` then trims up to 3 trailing zeros.
* **Go** `cedar-go/types/decimal.go:181-188` — `MarshalJSON()` emits `String()`,
  so the trim leaks into the wire.

## Does this affect policy decisions?

**No.** Decimal `==`, `<`, etc. compare the underlying `i64` value field
(`tenThousandths` in Go, identical i64 in Rust). Tested via:

* `policy_eval_decimal.cedar`: `permit when resource.balance == decimal("1.2300")`
* `entities_decimal_padded.json` (arg `"1.2300"`) and `entities_decimal_canonical.json` (arg `"1.23"`)

```
== Rust cedar CLI: padded  ==  ALLOW
== Rust cedar CLI: canonical == ALLOW
canonical-arg "1.23"             decision=allow   (cedar-go)
padded-arg "1.2300"              decision=allow   (cedar-go)
```

Both impls agree on the policy decision in all four combinations. The divergence is
strictly in **wire/display format**, not in semantics.

## Why this is still publishable

1. **Wire-format byte-inequality.** Any persistence layer or proxy that hashes /
   signs / diffs the JSON form of an entity attribute will see Rust-emitted blobs
   and Go-emitted blobs as distinct, even though they decode to the same Cedar value.
   Concretely demonstrated above for 3 of 4 inputs.
2. **Cross-impl audit-log mismatch.** If a Rust authoriser logs `decimal("1.2300")`
   and a Go replica logs `decimal("1.23")` for the *same* entity, log-shipping diff
   tooling will (incorrectly) flag drift.
3. **Asymmetry of canonicalisation policy.** Go silently canonicalises; Rust
   silently preserves. Neither matches the formal Lean spec yet (Lean wiring TODO).
   This is exactly the kind of unspecified, impl-dependent behaviour that fuzz/diff
   testing should expose.

## Reproducer paths

* `experiments/phase_e_real_bugs/decimal_repro/rust/{Cargo.toml,main.rs}` —
  build inside container with `cargo +1.94.0 build --release` (Cargo 1.82.0
  cannot resolve `time-0.3.47` which needs edition2024).
* `experiments/phase_e_real_bugs/decimal_repro/go/{go.mod,main.go}` — `go run .`
* `experiments/phase_e_real_bugs/decimal_repro/go_eval/{go.mod,main.go}` — policy
  decision check.
* `experiments/phase_e_real_bugs/ipaddr_repro/go_wire/{go.mod,main.go}` — wire
  round-trip (covers both decimal and ipaddr).

---

**Honest classification:** purely cosmetic at the evaluator level; concrete
wire-format divergence on JSON round-trip; not a policy-decision divergence.
