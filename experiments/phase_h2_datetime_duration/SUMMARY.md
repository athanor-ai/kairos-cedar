# Phase H2 — Datetime/Duration Drift Investigation

**Purpose:** Empirically test §7.4 prediction — same drift class on datetime + duration.

- Implementations: cedar-policy 4.10.0 (Rust) vs cedar-go v1.6.0 (commit `a9a4b1b`)
- Image: `ghcr.io/athanor-ai/kairos-cedar:latest`
- Tuples: 200

## Aggregate by classification

| classification | count |
|---|---|
| agreement_allow | 58 |
| agreement_both_reject | 118 |
| agreement_deny | 6 |
| asymmetric_path_both_deny | 2 |
| evaluator_disagreement | 16 |

## Per-shape breakdown

| shape | N | evaluator_diss | semantic_diss | both_reject | agreement |
|---|---|---|---|---|---|
| h1_datetime_equality | 52 | 6 | 0 | 33 | 13 |
| h1_datetime_parse | 52 | 5 | 0 | 33 | 13 |
| h2_duration_equality | 45 | 0 | 0 | 26 | 19 |
| h2_duration_parse | 45 | 0 | 0 | 26 | 19 |
| h3_expanded_year | 6 | 5 | 0 | 0 | 0 |

## Disagreements (16)

### `h1_datetime_parse__h1_dt_dt_expanded_year_pos` — evaluator_disagreement

```cedar
permit(principal, action, resource) when { datetime("+000000001-01-01T00:00:00Z") < datetime("2030-01-01T00:00:00Z") };
```

- rust decision: `Deny`
- rust output: `DENY

error while evaluating policy `policy0`: error while evaluating `datetime` extension function: invalid date pattern`
- go decision: `Allow`
- go output: ``

### `h1_datetime_parse__h1_dt_dt_expanded_year_neg` — evaluator_disagreement

```cedar
permit(principal, action, resource) when { datetime("-000000001-01-01T00:00:00Z") < datetime("2030-01-01T00:00:00Z") };
```

- rust decision: `Deny`
- rust output: `DENY

error while evaluating policy `policy0`: error while evaluating `datetime` extension function: invalid date pattern`
- go decision: `Allow`
- go output: ``

### `h1_datetime_parse__h1_dt_dt_expanded_year_2000` — evaluator_disagreement

```cedar
permit(principal, action, resource) when { datetime("+000002000-01-01T00:00:00Z") < datetime("2030-01-01T00:00:00Z") };
```

- rust decision: `Deny`
- rust output: `DENY

error while evaluating policy `policy0`: error while evaluating `datetime` extension function: invalid date pattern`
- go decision: `Allow`
- go output: ``

### `h1_datetime_parse__h1_dt_dt_expanded_year_date_only` — evaluator_disagreement

```cedar
permit(principal, action, resource) when { datetime("+000002025-04-25") < datetime("2030-01-01T00:00:00Z") };
```

- rust decision: `Deny`
- rust output: `DENY

error while evaluating policy `policy0`: error while evaluating `datetime` extension function: invalid date pattern`
- go decision: `Allow`
- go output: ``

### `h1_datetime_parse__h1_dt_dt_expanded_year_neg_date` — evaluator_disagreement

```cedar
permit(principal, action, resource) when { datetime("-000000001-01-01") < datetime("2030-01-01T00:00:00Z") };
```

- rust decision: `Deny`
- rust output: `DENY

error while evaluating policy `policy0`: error while evaluating `datetime` extension function: invalid date pattern`
- go decision: `Allow`
- go output: ``

### `h1_datetime_equality__h1_dt_eq_dt_expanded_year_pos` — evaluator_disagreement

```cedar
permit(principal, action, resource) when { datetime("+000000001-01-01T00:00:00Z") == datetime("+000000001-01-01T00:00:00Z") };
```

- rust decision: `Deny`
- rust output: `DENY

error while evaluating policy `policy0`: error while evaluating `datetime` extension function: invalid date pattern`
- go decision: `Allow`
- go output: ``

### `h1_datetime_equality__h1_dt_eq_dt_expanded_year_neg` — evaluator_disagreement

```cedar
permit(principal, action, resource) when { datetime("-000000001-01-01T00:00:00Z") == datetime("-000000001-01-01T00:00:00Z") };
```

- rust decision: `Deny`
- rust output: `DENY

error while evaluating policy `policy0`: error while evaluating `datetime` extension function: invalid date pattern`
- go decision: `Allow`
- go output: ``

### `h1_datetime_equality__h1_dt_eq_dt_expanded_year_2000` — evaluator_disagreement

```cedar
permit(principal, action, resource) when { datetime("+000002000-01-01T00:00:00Z") == datetime("+000002000-01-01T00:00:00Z") };
```

- rust decision: `Deny`
- rust output: `DENY

error while evaluating policy `policy0`: error while evaluating `datetime` extension function: invalid date pattern`
- go decision: `Allow`
- go output: ``

### `h1_datetime_equality__h1_dt_eq_dt_expanded_year_9dig` — evaluator_disagreement

```cedar
permit(principal, action, resource) when { datetime("+000009999-12-31T23:59:59.999Z") == datetime("+000009999-12-31T23:59:59.999Z") };
```

- rust decision: `Deny`
- rust output: `DENY

error while evaluating policy `policy0`: error while evaluating `datetime` extension function: invalid date pattern`
- go decision: `Allow`
- go output: ``

### `h1_datetime_equality__h1_dt_eq_dt_expanded_year_date_only` — evaluator_disagreement

```cedar
permit(principal, action, resource) when { datetime("+000002025-04-25") == datetime("+000002025-04-25") };
```

- rust decision: `Deny`
- rust output: `DENY

error while evaluating policy `policy0`: error while evaluating `datetime` extension function: invalid date pattern`
- go decision: `Allow`
- go output: ``

### `h1_datetime_equality__h1_dt_eq_dt_expanded_year_neg_date` — evaluator_disagreement

```cedar
permit(principal, action, resource) when { datetime("-000000001-01-01") == datetime("-000000001-01-01") };
```

- rust decision: `Deny`
- rust output: `DENY

error while evaluating policy `policy0`: error while evaluating `datetime` extension function: invalid date pattern`
- go decision: `Allow`
- go output: ``

### `h3_expanded_year__h3_exp_year_0` — evaluator_disagreement

```cedar
permit(principal, action, resource) when { datetime("+000000001-01-01T00:00:00Z") < datetime("2000-01-01T00:00:00Z") };
```

- rust decision: `Deny`
- rust output: `DENY

error while evaluating policy `policy0`: error while evaluating `datetime` extension function: invalid date pattern`
- go decision: `Allow`
- go output: ``

### `h3_expanded_year__h3_exp_year_1` — evaluator_disagreement

```cedar
permit(principal, action, resource) when { datetime("+000002025-04-25T00:00:00Z") < datetime("9999-12-31T23:59:59Z") };
```

- rust decision: `Deny`
- rust output: `DENY

error while evaluating policy `policy0`: error while evaluating `datetime` extension function: invalid date pattern`
- go decision: `Allow`
- go output: ``

### `h3_expanded_year__h3_exp_year_2` — evaluator_disagreement

```cedar
permit(principal, action, resource) when { datetime("-000000001-12-31T23:59:59Z") < datetime("1970-01-01T00:00:00Z") };
```

- rust decision: `Deny`
- rust output: `DENY

error while evaluating policy `policy0`: error while evaluating `datetime` extension function: invalid date pattern`
- go decision: `Allow`
- go output: ``

### `h3_expanded_year__h3_exp_year_4` — evaluator_disagreement

```cedar
permit(principal, action, resource) when { datetime("+000000001-01-01") < datetime("2000-01-01") };
```

- rust decision: `Deny`
- rust output: `DENY

error while evaluating policy `policy0`: error while evaluating `datetime` extension function: invalid date pattern`
- go decision: `Allow`
- go output: ``

### `h3_expanded_year__h3_exp_year_5` — evaluator_disagreement

```cedar
permit(principal, action, resource) when { datetime("-000000001-01-01T00:00:00Z") < datetime("0001-01-01T00:00:00Z") };
```

- rust decision: `Deny`
- rust output: `DENY

error while evaluating policy `policy0`: error while evaluating `datetime` extension function: invalid date pattern`
- go decision: `Allow`
- go output: ``


## Predicted-vs-found analysis

**§7.4 prediction status: Confirmed for datetime (finding B2.3). Not confirmed for duration on inputs probed.**

The §7.4 prediction was that datetime and duration would exhibit the same 'stdlib superset' drift class as decimal (B2.1) and ipaddr (B2.2). The probe found **16 decision-flipping disagreements**: 16 in datetime shapes, 0 in duration shapes.

### Datetime — prediction confirmed (B2.3)

**Root cause:** cedar-go v1.6.0 implements Cedar RFC 110 (ISO 8601 expanded-year format `(+|-)YYYYYYYYY-MM-DD[T...]`) while cedar-policy 4.10.0 (Rust) does not. cedar-go's `ParseDatetime` (`cedar-go/types/datetime.go`, lines 106–125) branches on a leading `+` or `-` and sets `yearLength = 9`. The Rust implementation uses `DATE_PATTERN = r"^([0-9]{4})-..."` (exactly 4 digits, no sign prefix). The Lean reference spec (`checkComponentLen`) splits on `-` and requires `year.length == 4`.

Any `permit-when` policy whose condition calls `datetime("(+|-)DDDDDDDDD-MM-DD...")` where the cedar-go evaluation of the subsequent comparison yields true produces a **decision-flip**: cedar-go allows the request, cedar-policy denies it.

**Canonical example:**
```cedar
permit(principal, action, resource) when {
  datetime("+000000001-01-01T00:00:00Z") < datetime("2030-01-01T00:00:00Z")
};
```
cedar-policy 4.10.0 → **Deny** ("invalid date pattern"). cedar-go v1.6.0 → **Allow** (year 1 < year 2030, true).

Full reproducer: `disagreements/h1_datetime_parse/CANONICAL_REPRO.md`.

**Mechanistic note:** B2.1 (decimal) and B2.2 (ipaddr) are caused by cedar-go delegating to Go stdlib functions (`strconv.ParseInt`, `net/netip.ParseAddr`) that accept supersets of Cedar's grammar. B2.3 (datetime) is caused by cedar-go implementing a newer RFC revision. Both are instances of the same architectural pattern: **extension-type parser boundaries are where implementation divergence concentrates**, whether the cause is stdlib permissiveness or RFC version skew.

### Duration — prediction not confirmed on inputs probed

**0 disagreements** across 90 duration tuples. cedar-go's `ParseDuration` is a hand-rolled left-to-right parser with no stdlib delegation (contrast with decimal's `strconv.ParseInt`). The Rust implementation uses a regex. Inputs tested: leading `+`, decimal quantities, ISO 8601 forms, wrong-order units, duplicate units, whitespace, very large values, zero forms, negative zero. Both implementations rejected identical invalid inputs and accepted identical valid inputs.

The §7.4 prediction for duration was not confirmed and cannot be claimed confirmed or refuted without additional probing of inputs not yet exercised. The honest statement: the prediction held for datetime; duration did not exhibit observable drift on the inputs we exercised.

### Implication for §7.4 paper text

The section should be updated: datetime exhibits finding B2.3 (expanded-year RFC 110 divergence, decision-flipping, 16 distinct policies); duration does not exhibit drift on the inputs tested. The claim "we predict the same drift class on datetime and duration" should narrow to: "We confirmed the prediction for datetime (finding B2.3) and did not find drift in duration on the inputs we exercised; the prediction for duration remains untested beyond the inputs probed."

