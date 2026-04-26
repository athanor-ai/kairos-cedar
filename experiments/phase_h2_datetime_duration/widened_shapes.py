"""
Widened shapes for phase_h2; datetime + duration drift investigation.

Investigates the §7.4 prediction from the kairos-cedar paper:
"Cedar ships four extension types (decimal, ipaddr, datetime, duration); we
tested two and both drifted. We predict the same drift class on datetime and
duration."

The drift class for decimal (B2.1) and ipaddr (B2.2) is:
  cedar-go ext-type parsers delegate to Go stdlib functions whose accepted
  languages are strict supersets of the Cedar grammar.

For datetime and duration, the cedar-go parsers are hand-rolled (no stdlib
delegation), so the hypothesis needs independent verification.

Each tuple: same schema/entities as phase_c_diff/bug-hunt-2026-04-25.
"""

from __future__ import annotations
from typing import Any


def _wrap(body: str) -> str:
    return f'permit(principal, action, resource) when {{ {body} }};'


# ──────────────────────────────────────────────────────────────────
# H1: Datetime parse drift
#
# Cedar grammar (RFC 80):
#   YYYY-MM-DD
#   YYYY-MM-DDThh:mm:ssZ
#   YYYY-MM-DDThh:mm:ss.SSSZ
#   YYYY-MM-DDThh:mm:ss(+|-)hhmm
#   YYYY-MM-DDThh:mm:ss.SSS(+|-)hhmm
#
# Cedar RFC 110 (extended year):
#   (+|-)YYYYYYYYY-MM-DD[T...]
#
# Rust parse_datetime: uses DATE_PATTERN = r"^([0-9]{4})-..." (4 digits, no sign)
#   → does NOT support RFC 110 expanded year
# Lean parse: checkComponentLen requires year.length == 4 (no sign)
#   → does NOT support RFC 110 expanded year
# cedar-go ParseDatetime: explicitly supports +/- prefix with 9-digit year
#   → DOES support RFC 110 expanded year
#
# HYPOTHESIS: inputs using expanded year format (+/-)YYYYYYYYY accepted by
# cedar-go but rejected by Rust reference → decision-flip on permit-when policies.
# ──────────────────────────────────────────────────────────────────

DATETIME_LITERALS = [
    # ── Canonical (must agree: both accept) ──
    ("dt_canon_date_only",          "2025-04-25"),
    ("dt_canon_utc",                "2025-04-25T12:00:00Z"),
    ("dt_canon_utc_ms",             "2025-04-25T12:00:00.123Z"),
    ("dt_canon_offset_pos",         "2025-04-25T12:00:00+0530"),
    ("dt_canon_offset_neg",         "2025-04-25T12:00:00-0500"),
    ("dt_canon_offset_ms",          "2025-04-25T12:00:00.500+0100"),
    ("dt_canon_year_min",           "0000-01-01T00:00:00Z"),
    ("dt_canon_year_max",           "9999-12-31T23:59:59.999Z"),
    ("dt_canon_pre_epoch",          "1969-12-31T23:59:59Z"),
    # ── RFC 110 expanded year (cedar-go accepts, Rust/Lean REJECT) ──
    # key hypothesis cases; PREDICT decision-flip
    ("dt_expanded_year_pos",        "+000000001-01-01T00:00:00Z"),
    ("dt_expanded_year_neg",        "-000000001-01-01T00:00:00Z"),
    ("dt_expanded_year_2000",       "+000002000-01-01T00:00:00Z"),
    ("dt_expanded_year_9dig",       "+000009999-12-31T23:59:59.999Z"),
    ("dt_expanded_year_date_only",  "+000002025-04-25"),
    ("dt_expanded_year_neg_date",   "-000000001-01-01"),
    # ── Fractional seconds variants ──
    # cedar-go: parseUint reads exactly 3 digits
    # Rust regex: \.([0-9]{3}) requires exactly 3
    # So 1, 2, 4, 6-digit should both reject
    ("dt_ms_1digit",                "2025-04-25T00:00:00.1Z"),
    ("dt_ms_2digit",                "2025-04-25T00:00:00.12Z"),
    ("dt_ms_4digit",                "2025-04-25T00:00:00.1234Z"),
    ("dt_ms_6digit",                "2025-04-25T00:00:00.123456Z"),
    ("dt_ms_9digit",                "2025-04-25T00:00:00.123456789Z"),
    # ── Leap second (both should reject: second=60 invalid) ──
    ("dt_leap_second",              "2016-12-31T23:59:60Z"),
    # ── Timezone offset with colon (RFC 3339 style, NOT in Cedar spec) ──
    # cedar-go: expects +HHMM (no colon); Rust expects +HHMM (no colon)
    # Both should reject, but worth verifying
    ("dt_offset_colon_pos",         "2025-04-25T12:00:00+05:30"),
    ("dt_offset_colon_neg",         "2025-04-25T12:00:00-05:00"),
    ("dt_offset_colon_z",           "2025-04-25T12:00:00+00:00"),
    # ── Lowercase t/z (both should reject) ──
    ("dt_lowercase_t",              "2025-04-25t12:00:00Z"),
    ("dt_lowercase_z",              "2025-04-25T12:00:00z"),
    ("dt_lowercase_tz",             "2025-04-25t12:00:00z"),
    # ── Whitespace (both should reject) ──
    ("dt_lead_space",               " 2025-04-25T12:00:00Z"),
    ("dt_trail_space",              "2025-04-25T12:00:00Z "),
    # ── Offset boundary: +0000 should be valid UTC equivalent ──
    ("dt_offset_zero",              "2025-04-25T12:00:00+0000"),
    ("dt_offset_zero_neg",          "2025-04-25T12:00:00-0000"),
    # ── Offset out of range ──
    ("dt_offset_25h",               "2025-04-25T12:00:00+2500"),
    ("dt_offset_60m",               "2025-04-25T12:00:00+0060"),
    # ── Hour/minute/second out of range ──
    ("dt_hour_24",                  "2025-04-25T24:00:00Z"),
    ("dt_minute_60",                "2025-04-25T12:60:00Z"),
    ("dt_second_60",                "2025-04-25T12:00:60Z"),
    # ── Invalid date ──
    ("dt_feb_29_nonleap",           "2023-02-29T00:00:00Z"),
    ("dt_feb_29_leap",              "2024-02-29T00:00:00Z"),   # valid leap year
    ("dt_month_00",                 "2025-00-01T00:00:00Z"),
    ("dt_month_13",                 "2025-13-01T00:00:00Z"),
    ("dt_day_00",                   "2025-01-00T00:00:00Z"),
    ("dt_day_32",                   "2025-01-32T00:00:00Z"),
    # ── ISO 8601 duration string as datetime (should both reject) ──
    ("dt_iso_duration",             "P1D"),
    ("dt_iso_duration_t",           "PT1H"),
    # ── Special string values (should both reject) ──
    ("dt_now_keyword",              "now"),
    ("dt_today_keyword",            "today"),
    ("dt_unix_epoch",               "0"),
    # ── Missing T separator variants ──
    ("dt_no_t",                     "2025-04-25 12:00:00Z"),
    ("dt_no_separator",             "20250425T120000Z"),
    # ── Year with leading sign but only 4 digits (go: tries 9-digit → fail; rust: regex [0-9]{4} → fail) ──
    ("dt_short_pos_year",           "+2025-04-25T00:00:00Z"),  # go: needs 9 digits, fails; rust: regex requires no sign
    ("dt_short_neg_year",           "-2025-04-25T00:00:00Z"),  # same
    # ── Zero-padded offset ──
    ("dt_offset_pad",               "2025-04-25T12:00:00+0030"),
]


def shape_h1_datetime_parse() -> list[dict[str, Any]]:
    """Primary shape: datetime parse acceptance vs rejection.

    Policy: permit when { datetime("X") < datetime("2030-01-01T00:00:00Z") }
    If cedar-go accepts X but Rust rejects: cedar-go evaluates to Allow,
    Rust evaluates to Deny (parse error in permit-when → policy not satisfied).
    """
    out = []
    ref_dt = "2030-01-01T00:00:00Z"
    for (lit_id, lit) in DATETIME_LITERALS:
        if '"' in lit:
            continue
        body = f'datetime("{lit}") < datetime("{ref_dt}")'
        out.append({
            "sample_id": f"h1_dt_{lit_id}",
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(body),
            "context": {},
        })
    return out


def shape_h1_datetime_equality() -> list[dict[str, Any]]:
    """Equality checks: same datetime string on both sides.

    If cedar-go accepts but Rust rejects: Go → Allow (equal → true),
    Rust → Deny (parse error). Strong decision-flip signal.
    """
    out = []
    for (lit_id, lit) in DATETIME_LITERALS:
        if '"' in lit:
            continue
        # Same literal on both sides: if both parse, result is true (equality holds)
        body = f'datetime("{lit}") == datetime("{lit}")'
        out.append({
            "sample_id": f"h1_dt_eq_{lit_id}",
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(body),
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# H2: Duration parse drift
#
# Cedar grammar (RFC 80):
#   [-](Nd)?(Nh)?(Nm)?(Ns)?(Nms)?   (units in order, at least one pair)
#
# Rust parse_duration: uses regex r"^-?(([0-9]+)d)?(([0-9]+)h)?(([0-9]+)m)?(([0-9]+)s)?(([0-9]+)ms)?$"
#   Key: all groups optional, so the empty string "" only rejected by s.is_empty() check
#   Key: "-" alone rejected by `s == "-"` check
#   Key: regex allows all-zero groups omitted, so "0ms" matches fine
#
# cedar-go ParseDuration: hand-rolled left-to-right parser
#   Key: len(s) <= 1 rejects empty + single-char strings
#   Key: no '+' sign in negative check → rejects "+1s" (unexpected '+' char)
#   Key: requires at least one digit+unit pair → empty match after '-' rejects
#
# HYPOTHESIS: the regex in Rust accepts some strings that cedar-go's hand-
# rolled parser would reject, OR vice versa.
#
# Rust regex: r"^-?(([0-9]+)d)?(([0-9]+)h)?(([0-9]+)m)?(([0-9]+)s)?(([0-9]+)ms)?$"
# CRITICAL: this regex accepts "" (empty string, after '-' optional, all groups empty)
# but Rust has an explicit `s.is_empty()` pre-check.
# It also accepts "-" (only '-'), but Rust has an explicit `s == "-"` pre-check.
# It also matches "ms" (no digits before 'ms')! Wait - regex requires ([0-9]+) before each unit.
# Actually ([0-9]+)ms means 1+ digits required. So "ms" alone doesn't match.
# But what about just "-0ms"? That should match: -?(([0-9]+)ms)?$
#
# KEY: Rust regex has all groups OPTIONAL, meaning "-" followed by nothing
# could match if not for the explicit check. But "0d0h0m0s0ms" should match.
#
# What about all-zero group being omitted vs included?
# "1d" → all other groups empty → valid in both
# "" → rejected by both (explicit check in Rust, len<=1 in Go)
# "-" → rejected by both
# ──────────────────────────────────────────────────────────────────

DURATION_LITERALS = [
    # ── Canonical valid (both should accept) ──
    ("dur_1ms",         "1ms"),
    ("dur_1s",          "1s"),
    ("dur_1m",          "1m"),
    ("dur_1h",          "1h"),
    ("dur_1d",          "1d"),
    ("dur_0ms",         "0ms"),
    ("dur_0s",          "0s"),
    ("dur_compound",    "1d2h3m4s5ms"),
    ("dur_neg_1s",      "-1s"),
    ("dur_neg_comp",    "-1d2h3m4s5ms"),
    ("dur_max_units",   "1d23h59m59s999ms"),
    # ── Edge: single-char strings (cedar-go rejects len<=1) ──
    ("dur_single_d",    "d"),    # single char, no digits → both should reject
    ("dur_single_s",    "s"),    # single char, no digits → both should reject
    # ── Empty string (both reject) ──
    # Can't test "" in policy syntax easily, skip
    # ── Leading '+' sign (cedar-go: unexpected char; Rust regex: no '+' in pattern → no match) ──
    ("dur_pos_sign_1s",     "+1s"),
    ("dur_pos_sign_1d",     "+1d"),
    ("dur_pos_sign_comp",   "+1h30m"),
    # ── Duplicate units ──
    ("dur_dup_s",       "1s2s"),   # both should reject (s repeated)
    ("dur_dup_m",       "1m2m"),
    ("dur_dup_ms",      "1ms2ms"),
    # ── Wrong order ──
    ("dur_rev_order",   "1ms1s"),  # ms before s → wrong order
    ("dur_rev_ms_m",    "1ms1m"),  # ms before m → wrong order
    ("dur_rev_s_m",     "1s1m"),   # s before m → wrong order
    ("dur_rev_d_h",     "1h1d"),   # h before d → wrong order
    # ── Decimal in quantity (not in Cedar grammar) ──
    ("dur_decimal_s",   "1.5s"),   # not a valid Cedar duration
    ("dur_decimal_ms",  "0.5ms"),
    # ── ISO 8601 duration forms (not in Cedar grammar) ──
    ("dur_iso_p1d",     "P1D"),
    ("dur_iso_pt1h",    "PT1H"),
    ("dur_iso_p1dt1h",  "P1DT1H"),
    # ── Whitespace ──
    ("dur_lead_space",  " 1s"),
    ("dur_trail_space", "1s "),
    ("dur_inner_space", "1s 2ms"),
    # ── Just a minus sign (both reject) ──
    ("dur_just_minus",  "-"),
    # ── Minus with no value ──
    ("dur_minus_only",  "-d"),
    # ── Large values (overflow check) ──
    ("dur_very_large",  "9999999999999999999d"),
    ("dur_near_max",    "106751991167300d"),  # near i64 max in days
    # ── Zero-duration forms ──
    ("dur_zero_all",    "0d0h0m0s0ms"),  # all zero; Rust regex matches; cedar-go: does it?
    ("dur_zero_no_ms",  "0d0h0m0s"),
    ("dur_zero_d_only", "0d"),
    # ── Unit without quantity ──
    ("dur_no_digits_ms", "ms"),   # no leading digit
    ("dur_no_digits_s",  "s"),
    # ── Multiple consecutive digits (large but in range) ──
    ("dur_large_ms",    "9223372036854775ms"),  # near i64 max in ms
    ("dur_large_s",     "9223372036854s"),
    # ── Negative zero ──
    ("dur_neg_zero",    "-0ms"),
    ("dur_neg_zero_s",  "-0s"),
    ("dur_neg_comp_z",  "-0d0h0m0s0ms"),
]


def shape_h2_duration_parse() -> list[dict[str, Any]]:
    """Primary shape: duration parse acceptance vs rejection.

    Policy: permit when { duration("X") < duration("1d") }
    If cedar-go accepts X but Rust rejects: Go → Allow or Deny depending on value,
    Rust → Deny (parse error). Decision-flip if Go → Allow.
    """
    out = []
    ref_dur = "1d"
    for (lit_id, lit) in DURATION_LITERALS:
        if '"' in lit:
            continue
        body = f'duration("{lit}") < duration("{ref_dur}")'
        out.append({
            "sample_id": f"h2_dur_{lit_id}",
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(body),
            "context": {},
        })
    return out


def shape_h2_duration_equality() -> list[dict[str, Any]]:
    """Equality: same duration on both sides.

    If cedar-go accepts but Rust rejects: Go → Allow (equal), Rust → Deny.
    """
    out = []
    for (lit_id, lit) in DURATION_LITERALS:
        if '"' in lit:
            continue
        body = f'duration("{lit}") == duration("{lit}")'
        out.append({
            "sample_id": f"h2_dur_eq_{lit_id}",
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(body),
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# H3: Targeted expanded-year datetime probes
#   These are the highest-confidence hypothesis cases from static analysis.
# ──────────────────────────────────────────────────────────────────

EXPANDED_YEAR_CASES = [
    # Format: (sample_id, datetime_literal, comparison_datetime, expected_go_decision)
    # cedar-go accepts, Rust rejects → Go should reach a decision, Rust errors
    ("+000000001-01-01T00:00:00Z", "2000-01-01T00:00:00Z"),   # year 1 < year 2000
    ("+000002025-04-25T00:00:00Z", "9999-12-31T23:59:59Z"),   # year 2025 < year 9999
    ("-000000001-12-31T23:59:59Z", "1970-01-01T00:00:00Z"),   # negative year < 1970
    ("+000009999-12-31T23:59:59Z", "2030-01-01T00:00:00Z"),   # year 9999 > 2030 → false, still no error in Go
    ("+000000001-01-01",           "2000-01-01"),              # date-only expanded year
    ("-000000001-01-01T00:00:00Z", "0001-01-01T00:00:00Z"),   # negative year < 0001
]


def shape_h3_expanded_year() -> list[dict[str, Any]]:
    """Targeted expanded-year probes; highest confidence prediction cases."""
    out = []
    for i, (lit, ref) in enumerate(EXPANDED_YEAR_CASES):
        if '"' in lit or '"' in ref:
            continue
        body = f'datetime("{lit}") < datetime("{ref}")'
        out.append({
            "sample_id": f"h3_exp_year_{i}",
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(body),
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# Aggregate
# ──────────────────────────────────────────────────────────────────

ALL_SHAPES: dict[str, list[dict[str, Any]]] = {
    "h1_datetime_parse":    shape_h1_datetime_parse(),
    "h1_datetime_equality": shape_h1_datetime_equality(),
    "h2_duration_parse":    shape_h2_duration_parse(),
    "h2_duration_equality": shape_h2_duration_equality(),
    "h3_expanded_year":     shape_h3_expanded_year(),
}


def all_tuples() -> list[dict[str, Any]]:
    out = []
    for shape, tups in ALL_SHAPES.items():
        for t in tups:
            t = dict(t)
            t["shape"] = shape
            t["idx"] = f"{shape}__{t['sample_id']}"
            out.append(t)
    return out


if __name__ == "__main__":
    import json, sys
    tups = all_tuples()
    print(f"Total tuples: {len(tups)}", file=sys.stderr)
    for shape in ALL_SHAPES:
        print(f"  {shape}: {len(ALL_SHAPES[shape])}", file=sys.stderr)
    if "--dump" in sys.argv:
        for t in tups:
            print(json.dumps(t))
