"""
widened_shapes_v2.py  - Extended shape corpus for N=100k bug hunt (2026-04-26).

Builds on widened_shapes.py (206 tuples / 11 shapes from bug-hunt-2026-04-25)
by adding NEW shapes not previously covered. Each new shape targets a
cedar-go behavior that may diverge from cedar-policy (Rust reference).

New shape groups (this file, N=100k-scale total):
  Q1  - decimal arithmetic corner cases (over/under-flow, boundary arithmetic)
  Q2  - ipaddr additional edge cases (IPv4-mapped semantics, host-bits-set CIDR)
  Q3  - datetime comparison + duration arithmetic
  Q4  - string operations (like, in-set, contains, string coercion)
  Q5  - operator precedence + nested boolean
  Q6  - entity hierarchy (in/is) with depth + cycles
  Q7  - record/attribute access patterns
  Q8  - multi-policy (permit + forbid interaction)
  Q9  - decimal/ip cross-type comparisons
  Q10 - cedar-go namespace/type coercion corners
"""

from __future__ import annotations

import itertools
from typing import Any


def _wrap(expr: str) -> str:
    return f'permit(principal, action, resource) when {{ {expr} }};'


def _forbid_wrap(expr: str) -> str:
    return f'forbid(principal, action, resource) when {{ {expr} }};'


# ──────────────────────────────────────────────────────────────────
# Q1: Decimal arithmetic boundary + overload corners
# ──────────────────────────────────────────────────────────────────

def shape_q1_decimal_boundary() -> list[dict[str, Any]]:
    """Push decimal arithmetic to specification boundaries.
    Cedar spec: 4 fractional digits max, value in [-922337203685477.5808, +922337203685477.5807].
    Focus: boundary arithmetic, sign semantics, comparison order.
    """
    out = []
    cases = [
        # lessThan / greaterThan on max+epsilon vs max (should both reject or agree)
        ("q1_max_lt_max",      'decimal("922337203685477.5807").lessThan(decimal("922337203685477.5807"))'),
        ("q1_max_le_max",      'decimal("922337203685477.5807").lessThanOrEqual(decimal("922337203685477.5807"))'),
        ("q1_min_gt_min",      'decimal("-922337203685477.5808").greaterThan(decimal("-922337203685477.5808"))'),
        ("q1_min_ge_min",      'decimal("-922337203685477.5808").greaterThanOrEqual(decimal("-922337203685477.5808"))'),
        # Reflexive equality through ops
        ("q1_zero_eq_negzero", 'decimal("0.0").lessThan(decimal("-0.0")) || decimal("-0.0").lessThan(decimal("0.0"))'),
        ("q1_zero_ge_negzero", 'decimal("0.0").greaterThanOrEqual(decimal("-0.0"))'),
        # lessThan chained
        ("q1_chain_lt",        'decimal("0.0001").lessThan(decimal("0.0002"))'),
        ("q1_chain_lt2",       'decimal("-0.0001").lessThan(decimal("0.0001"))'),
        ("q1_chain_lt3",       'decimal("0.9999").lessThan(decimal("1.0000"))'),
        # +sign variants (B1 class - already found but new combo)
        ("q1_pos_sign_1",      'decimal("+1.0").lessThan(decimal("2.0"))'),
        ("q1_pos_sign_max",    'decimal("+922337203685477.5807").lessThan(decimal("922337203685477.5807"))'),
        ("q1_pos_sign_100",    'decimal("+100.5000").greaterThan(decimal("100.4999"))'),
        # Double-parse: apply op to two non-canonical decimals
        ("q1_both_trailing_z", 'decimal("0.10").lessThan(decimal("0.20"))'),
        ("q1_both_lead_zero",  'decimal("01.0000").lessThan(decimal("02.0000"))'),
        # Over-precision (5+ fractional digits) - should both reject
        ("q1_5_frac",         'decimal("0.12345").lessThan(decimal("0.5"))'),
        ("q1_5_frac_neg",     'decimal("-0.12345").lessThan(decimal("0.5"))'),
        ("q1_8_frac",         'decimal("0.12345678").lessThan(decimal("0.5"))'),
        # Whitespace variants
        ("q1_lead_space",     'decimal(" 1.0").lessThan(decimal("2.0"))'),
        ("q1_trail_space",    'decimal("1.0 ").lessThan(decimal("2.0"))'),
        ("q1_mid_space",      'decimal("1. 0").lessThan(decimal("2.0"))'),
        # Exponent notation
        ("q1_exp_lower",      'decimal("1e2").lessThan(decimal("200.0"))'),
        ("q1_exp_upper",      'decimal("1E2").lessThan(decimal("200.0"))'),
        ("q1_exp_neg",        'decimal("1e-2").lessThan(decimal("0.5"))'),
        # nan-like
        ("q1_nan_str",        'decimal("nan").lessThan(decimal("0.5"))'),
        ("q1_inf_str",        'decimal("inf").lessThan(decimal("0.5"))'),
        # empty string
        ("q1_empty",          'decimal("").lessThan(decimal("0.5"))'),
        # non-numeric
        ("q1_alpha",          'decimal("abc").lessThan(decimal("0.5"))'),
        # Only dot
        ("q1_only_dot",       'decimal(".").lessThan(decimal("0.5"))'),
        # Only minus
        ("q1_only_minus",     'decimal("-").lessThan(decimal("0.5"))'),
    ]
    for label, expr in cases:
        out.append({
            "sample_id": label,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(expr),
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# Q2: ipaddr additional edge cases
# ──────────────────────────────────────────────────────────────────

def shape_q2_ip_extra() -> list[dict[str, Any]]:
    """Additional IP address cases not fully explored in bug-hunt-2026-04-25."""
    out = []
    cases = [
        # Zone identifiers (already found but more variants)
        ("q2_zone_eth1",      'ip("fe80::1%eth1").isIpv6()'),
        ("q2_zone_en0",       'ip("fe80::2%en0").isIpv6()'),
        ("q2_zone_lo",        'ip("fe80::3%lo").isIpv6()'),
        ("q2_zone_long",      'ip("2001:db8::1%longinterface123").isIpv6()'),
        ("q2_zone_num",       'ip("fe80::4%1").isIpv6()'),
        # IPv4-mapped IPv6 semantics
        ("q2_v4mapped_isv4",  'ip("::ffff:192.0.2.1").isIpv4()'),
        ("q2_v4mapped_isv6",  'ip("::ffff:192.0.2.1").isIpv6()'),
        # IPv4-compat (deprecated but often parsed)
        ("q2_v4compat_isv4",  'ip("::192.0.2.1").isIpv4()'),
        ("q2_v4compat_isv6",  'ip("::192.0.2.1").isIpv6()'),
        # IPv4-mapped in range check
        ("q2_v4mapped_range", 'ip("::ffff:192.168.1.1").isInRange(ip("192.168.0.0/16"))'),
        # Leading zeros in IPv4 octets
        ("q2_v4_lead_zero_isv4", 'ip("010.0.0.1").isIpv4()'),
        ("q2_v4_lead_zero_loop", 'ip("127.000.000.001").isLoopback()'),
        # Host bits set in CIDR (10.0.0.5/8 has host bits set)
        ("q2_host_bits_v4",   'ip("10.0.0.5/8").isIpv4()'),
        ("q2_host_bits_inrange", 'ip("10.0.0.1").isInRange(ip("10.0.0.5/8"))'),
        # Boundary checks isLoopback for non-loopback in range
        ("q2_loop_range_v4",  'ip("127.0.0.1").isInRange(ip("127.0.0.0/8"))'),
        ("q2_loop_range_v6",  'ip("::1").isInRange(ip("::/0"))'),
        # isMulticast edge
        ("q2_multi_v4",       'ip("224.0.0.0").isMulticast()'),
        ("q2_multi_edge",     'ip("239.255.255.255").isMulticast()'),
        ("q2_non_multi",      'ip("240.0.0.0").isMulticast()'),
        ("q2_multi_v6",       'ip("ff02::1").isMulticast()'),
        ("q2_v6_multicast_global", 'ip("ff0e::1").isMulticast()'),
        # Link-local isLoopback
        ("q2_linklocal_loop", 'ip("fe80::1").isLoopback()'),
        # Loopback range
        ("q2_v4_loop_range",  'ip("127.255.255.255").isLoopback()'),
        # CIDR prefix operations
        ("q2_v6_prefix_inrange", 'ip("2001:db8::1").isInRange(ip("2001:db8::/32"))'),
        ("q2_v6_prefix_outside", 'ip("2001:db9::1").isInRange(ip("2001:db8::/32"))'),
        # /0 range covers everything
        ("q2_v4_zero_prefix",  'ip("1.2.3.4").isInRange(ip("0.0.0.0/0"))'),
        ("q2_v6_zero_prefix",  'ip("::1").isInRange(ip("::/0"))'),
        # /32 range (exact match)
        ("q2_v4_exact",        'ip("1.2.3.4").isInRange(ip("1.2.3.4/32"))'),
        ("q2_v4_exact_miss",   'ip("1.2.3.5").isInRange(ip("1.2.3.4/32"))'),
        # Empty string
        ("q2_empty_parse",    'ip("").isIpv4()'),
        # whitespace
        ("q2_lead_space",     'ip(" 127.0.0.1").isIpv4()'),
        # Subnet notation with plus sign
        ("q2_plus_sign_ip",   'ip("+127.0.0.1").isIpv4()'),
    ]
    for label, expr in cases:
        out.append({
            "sample_id": label,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(expr),
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# Q3: datetime + duration comparison and arithmetic
# ──────────────────────────────────────────────────────────────────

def shape_q3_datetime_ops() -> list[dict[str, Any]]:
    """Cedar datetime/duration operations. cedar-go ships these as built-ins;
    cedar-policy requires them too. Testing drift in comparison semantics,
    duration parsing, and epoch offsets."""
    out = []
    cases = [
        # Basic comparison operators
        ("q3_dt_lt",          'datetime("2024-01-01T00:00:00Z") < datetime("2025-01-01T00:00:00Z")'),
        ("q3_dt_gt",          'datetime("2025-01-01T00:00:00Z") > datetime("2024-01-01T00:00:00Z")'),
        ("q3_dt_eq",          'datetime("2025-04-25T00:00:00Z") == datetime("2025-04-25T00:00:00Z")'),
        ("q3_dt_neq",         'datetime("2025-04-25T00:00:00Z") != datetime("2024-04-25T00:00:00Z")'),
        # Duration parsing
        ("q3_dur_basic",      'duration("1d").toSeconds() > 0'),
        ("q3_dur_hours",      'duration("24h").toSeconds() == 86400'),
        ("q3_dur_mins",       'duration("60m").toSeconds() == 3600'),
        ("q3_dur_secs",       'duration("86400s").toSeconds() == 86400'),
        ("q3_dur_ms",         'duration("1000ms").toSeconds() == 1'),
        ("q3_dur_mixed",      'duration("1d2h3m4s").toSeconds() > 0'),
        # Duration comparison
        ("q3_dur_lt",         'duration("1d") < duration("2d")'),
        ("q3_dur_gt",         'duration("2d") > duration("1d")'),
        ("q3_dur_eq",         'duration("24h") == duration("24h")'),
        # Duration arithmetic on datetime
        ("q3_dt_offset",      'datetime("2025-04-25T12:00:00Z").offset(duration("1h")) > datetime("2025-04-25T12:00:00Z")'),
        ("q3_dt_dur_before",  'datetime("2025-04-25T12:00:00Z").durationSince(datetime("2025-04-25T11:00:00Z")) == duration("1h")'),
        # Edge: leap year
        ("q3_leap_day",       'datetime("2024-02-29T00:00:00Z") < datetime("2024-03-01T00:00:00Z")'),
        ("q3_non_leap",       'datetime("2023-02-28T00:00:00Z") < datetime("2023-03-01T00:00:00Z")'),
        # Edge: milliseconds
        ("q3_ms_precision",   'datetime("2025-04-25T00:00:00.001Z") > datetime("2025-04-25T00:00:00.000Z")'),
        ("q3_ms_4_digits",    'datetime("2025-04-25T00:00:00.1234Z") > datetime("2025-04-25T00:00:00.000Z")'),
        # Edge: timezone offsets in comparison
        ("q3_tz_utc_plus5",   'datetime("2025-04-25T12:00:00+05:00") < datetime("2025-04-25T12:00:00Z")'),
        ("q3_tz_utc_minus5",  'datetime("2025-04-25T12:00:00-05:00") > datetime("2025-04-25T12:00:00Z")'),
        # Pre-epoch
        ("q3_pre_epoch",      'datetime("1969-12-31T23:59:59Z") < datetime("1970-01-01T00:00:00Z")'),
        # Far future
        ("q3_far_future",     'datetime("2099-12-31T23:59:59Z") > datetime("2025-04-25T00:00:00Z")'),
        # Invalid duration strings
        ("q3_dur_empty",      'duration("").toSeconds() == 0'),
        ("q3_dur_invalid",    'duration("abc").toSeconds() == 0'),
        ("q3_dur_neg",        'duration("-1d").toSeconds() < 0'),
        # Duration toMilliseconds
        ("q3_dur_toMs",       'duration("1s").toMilliseconds() == 1000'),
        ("q3_dur_toMs_ms",    'duration("500ms").toMilliseconds() == 500'),
        # datetime toUnixTimeSeconds
        ("q3_epoch_unix",     'datetime("1970-01-01T00:00:00Z").toUnixTimeSeconds() == 0'),
        ("q3_epoch_plus1",    'datetime("1970-01-01T00:00:01Z").toUnixTimeSeconds() == 1'),
    ]
    for label, expr in cases:
        out.append({
            "sample_id": label,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(expr),
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# Q4: String operations and like patterns
# ──────────────────────────────────────────────────────────────────

def shape_q4_string_ops() -> list[dict[str, Any]]:
    """String expression evaluation: like, equality, contains-style checks."""
    out = []
    cases = [
        # Basic like
        ("q4_like_exact",     '"hello" like "hello"'),
        ("q4_like_star_all",  '"anything" like "*"'),
        ("q4_like_star_pre",  '"hello" like "*lo"'),
        ("q4_like_star_suf",  '"hello" like "he*"'),
        ("q4_like_star_mid",  '"hello" like "h*o"'),
        ("q4_like_no_match",  '"hello" like "world"'),
        ("q4_like_empty_str", '"" like ""'),
        ("q4_like_empty_pat", '"hello" like ""'),
        ("q4_like_star_empty","" ' like "*"'),
        # Escaped star in pattern
        ("q4_like_esc_star",  '"a*b" like "a\\\\*b"'),
        # Double backslash in string
        ("q4_like_dbl_slash", '"a\\\\b" like "a\\\\\\\\b"'),
        # Unicode in like
        ("q4_like_unicode",   '"caf\\u{E9}" like "caf*"'),
        # String equality
        ("q4_str_eq",         '"hello" == "hello"'),
        ("q4_str_ne",         '"hello" != "world"'),
        # String in set
        ("q4_str_in_set",     '"view" in ["view", "edit", "admin"]'),
        ("q4_str_not_in_set", '"delete" in ["view", "edit"]'),
        # Long string
        ("q4_long_str",       '"' + 'a' * 1000 + '" like "*"'),
        # Null byte (Cedar string literals: unclear if \u{0} is valid)
        ("q4_null_byte",      '"\\u{0}" like "*"'),
        # Unicode normalization (NFC vs NFD)
        ("q4_nfc_nfd_eq",     '"caf\\u{E9}" == "cafe\\u{301}"'),
        # String with embedded newline
        ("q4_newline",        '"hello\\nworld" like "hello*world"'),
        # Case sensitivity
        ("q4_case_sens",      '"Hello" == "hello"'),
        ("q4_case_like",      '"Hello" like "hello"'),
    ]
    for label, expr in cases:
        out.append({
            "sample_id": label,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(expr),
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# Q5: Operator precedence + nested boolean
# ──────────────────────────────────────────────────────────────────

def shape_q5_precedence() -> list[dict[str, Any]]:
    """Test Cedar's operator precedence: && binds tighter than ||; ! unary.
    Also test short-circuit with ext-type errors for new combinations."""
    out = []
    cases = [
        # Basic precedence
        ("q5_and_or_prec",    'true || false && false'),  # should be true (AND binds tighter)
        ("q5_or_and_prec",    'false && true || true'),   # should be true
        ("q5_not_and",        '!false && true'),
        ("q5_not_or",         '!true || true'),
        ("q5_not_not",        '!!true'),
        # Comparison + boolean
        ("q5_cmp_and",        '1 == 1 && 2 == 2'),
        ("q5_cmp_or",         '1 == 2 || 2 == 2'),
        ("q5_cmp_not",        '!(1 == 2)'),
        # Nested ternary (if-then-else)
        ("q5_ite_basic",      'if true then true else false'),
        ("q5_ite_nested",     'if (if true then false else true) then false else true'),
        ("q5_ite_both_false", 'if false then true else false'),
        # Short-circuit with zone-id (new combo)
        ("q5_sc_zone_and",    'false && ip("fe80::1%eth0").isIpv6()'),
        ("q5_sc_zone_or",     'true || ip("fe80::1%eth0").isIpv6()'),
        ("q5_sc_zone_true_and", 'true && ip("fe80::1%eth0").isIpv6()'),
        # Short-circuit with +sign decimal
        ("q5_sc_dec_plus_and", 'false && decimal("+1.0").lessThan(decimal("2.0"))'),
        ("q5_sc_dec_plus_or",  'true || decimal("+1.0").lessThan(decimal("2.0"))'),
        ("q5_sc_dec_plus_true", 'true && decimal("+1.0").lessThan(decimal("2.0"))'),
        # Double negation
        ("q5_dbl_neg",        '!!(1 == 1)'),
        ("q5_triple_neg",     '!!!(1 == 2)'),
        # Mixed ext type with short circuit
        ("q5_sc_dt_false",    'false && datetime("invalid-date") < datetime("2025-01-01T00:00:00Z")'),
        ("q5_sc_dt_true",     'true || datetime("invalid-date") < datetime("2025-01-01T00:00:00Z")'),
    ]
    for label, expr in cases:
        out.append({
            "sample_id": label,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(expr),
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# Q6: Entity hierarchy (in / is)
# ──────────────────────────────────────────────────────────────────

def shape_q6_entity_hierarchy() -> list[dict[str, Any]]:
    """Test entity hierarchy traversal. Uses the widened schema from
    run_widened.py: User in [Group], Group, Document in [Document]."""
    out = []
    cases = [
        # Principal `in` group membership
        ("q6_alice_in_users",   'principal in Group::"users"'),
        ("q6_alice_in_admins",  'principal in Group::"admins"'),  # alice is NOT in admins
        ("q6_bob_in_admins",    'User::"bob" in Group::"admins"'),
        ("q6_carol_in_viewers", 'User::"carol" in Group::"viewers"'),
        # `is` type check
        ("q6_alice_is_user",    'principal is User'),
        ("q6_alice_is_group",   'principal is Group'),  # should be false
        # Resource `is` type check
        ("q6_doc1_is_doc",      'resource is Document'),
        ("q6_doc1_is_photo",    'resource is Photo'),
        # Compound: is + in
        ("q6_is_and_in",        'principal is User && principal in Group::"users"'),
        ("q6_is_and_wrong_in",  'principal is User && principal in Group::"admins"'),
        # Entity in set
        ("q6_principal_in_set", 'principal in [User::"alice", User::"bob"]'),
        ("q6_action_in_set",    'action in [Action::"view", Action::"edit"]'),
        ("q6_action_not_in_set", 'action in [Action::"admin"]'),
        # Deep hierarchy: alice -> users (depth 1)
        ("q6_transitive_1",     'User::"alice" in Group::"users"'),
        # alice NOT in admins
        ("q6_not_in_admins",    '!(User::"alice" in Group::"admins")'),
        # resource in-set check
        ("q6_res_in_set",       'resource in [Document::"doc1", Document::"doc2"]'),
        ("q6_res_not_in_set",   'resource in [Document::"doc2"]'),  # alice + doc1 → false
        # type check with negation
        ("q6_not_is_group",     '!(principal is Group)'),
        # Combined multi-level
        ("q6_combined_all",     'principal is User && resource is Document && action == Action::"view"'),
    ]
    for label, expr in cases:
        out.append({
            "sample_id": label,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(expr),
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# Q7: Record / attribute access
# ──────────────────────────────────────────────────────────────────

def shape_q7_records() -> list[dict[str, Any]]:
    """Record construction and attribute access in Cedar."""
    out = []
    cases = [
        # Record construction + attribute read
        ("q7_rec_has",          '{"key": true} has key'),
        ("q7_rec_has_absent",   '{"key": true} has missing_key'),
        ("q7_rec_get",          '{"key": 42}.key == 42'),
        ("q7_rec_nested",       '{"outer": {"inner": true}}.outer.inner'),
        ("q7_rec_nested_has",   '{"outer": {"inner": true}}.outer has inner'),
        # Record with string key
        ("q7_rec_str_key",      '{"answer": "yes"}.answer == "yes"'),
        # Record with multiple entries
        ("q7_rec_multi",        '{"a": 1, "b": 2, "c": 3}.b == 2'),
        # Record equality
        ("q7_rec_eq",           '{"a": 1, "b": 2} == {"a": 1, "b": 2}'),
        ("q7_rec_ne",           '{"a": 1} != {"a": 2}'),
        # Nested record has
        ("q7_deep_has",         '{"a": {"b": {"c": 42}}}.a.b has c'),
        ("q7_deep_get",         '{"a": {"b": {"c": 42}}}.a.b.c == 42'),
        # Record with extension type value
        ("q7_rec_decimal",      '{"val": decimal("1.5")}.val.lessThan(decimal("2.0"))'),
        ("q7_rec_ip",           '{"addr": ip("127.0.0.1")}.addr.isLoopback()'),
        # Empty record
        ("q7_empty_rec",        '{} == {}'),
        ("q7_empty_has",        '{} has key'),
        # Boolean value in record
        ("q7_rec_bool",         '{"flag": true}.flag'),
        ("q7_rec_bool_not",     '!{"flag": false}.flag'),
    ]
    for label, expr in cases:
        out.append({
            "sample_id": label,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(expr),
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# Q8: Multi-policy (permit + forbid interaction)
# ──────────────────────────────────────────────────────────────────

def shape_q8_multi_policy() -> list[dict[str, Any]]:
    """Test permit+forbid interactions, priority rules, and complex policy sets."""
    out = []
    cases = [
        # forbid overrides permit
        ("q8_forbid_overrides",
         'permit(principal, action, resource);\nforbid(principal, action, resource);'),
        # permit with no forbid
        ("q8_permit_only",
         'permit(principal, action, resource);'),
        # forbid with no permit
        ("q8_forbid_only",
         'forbid(principal, action, resource);'),
        # permit unless → same as permit + forbid when
        ("q8_permit_unless_false",
         'permit(principal, action, resource) unless { false };'),
        ("q8_permit_unless_true",
         'permit(principal, action, resource) unless { true };'),
        # Multiple permits: any matching = Allow
        ("q8_multi_permit_first",
         'permit(principal == User::"alice", action, resource);\npermit(principal == User::"bob", action, resource);'),
        ("q8_multi_permit_neither",
         'permit(principal == User::"carol", action, resource);\npermit(principal == User::"bob", action, resource);'),
        # forbid specific action
        ("q8_forbid_admin",
         'permit(principal, action, resource);\nforbid(principal, action == Action::"admin", resource);'),
        # permit specific + forbid all
        ("q8_permit_specific_forbid_all",
         'permit(principal == User::"alice", action == Action::"view", resource == Document::"doc1");\nforbid(principal, action, resource);'),
        # Multiple forbids
        ("q8_multi_forbid",
         'permit(principal, action, resource);\nforbid(principal == User::"alice", action, resource);\nforbid(principal == User::"bob", action, resource);'),
        # Forbid on resource type
        ("q8_forbid_photo_type",
         'permit(principal, action, resource);\nforbid(principal, action, resource is Photo);'),
        # Complex condition
        ("q8_complex_cond",
         'permit(principal, action, resource) when { action == Action::"view" };\nforbid(principal, action, resource) when { resource == Document::"doc2" };'),
    ]
    for label, policy in cases:
        out.append({
            "sample_id": label,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": policy,
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# Q9: Arithmetic + integer operations
# ──────────────────────────────────────────────────────────────────

def shape_q9_arithmetic() -> list[dict[str, Any]]:
    """Cedar integer arithmetic: +, -, *, /, unary minus. Overflow behavior."""
    out = []
    MAX_I64 = 9223372036854775807
    MIN_I64 = -9223372036854775808
    cases = [
        # Basic ops
        ("q9_add",         '1 + 1 == 2'),
        ("q9_sub",         '5 - 3 == 2'),
        ("q9_mul",         '3 * 4 == 12'),
        ("q9_neg",         '-(5) == -5'),
        ("q9_neg_neg",     '-(-5) == 5'),
        # Larger values
        ("q9_add_large",   '1000000 + 2000000 == 3000000'),
        ("q9_mul_large",   '100000 * 100000 == 10000000000'),
        # Cedar integer is 64-bit signed: overflow should error in both
        ("q9_overflow_add", f'{MAX_I64} + 1 == 0'),
        ("q9_overflow_mul", f'1000000000 * 10000000000 == 0'),
        # Underflow
        ("q9_underflow_sub", f'{MIN_I64} - 1 == 0'),
        # Division (Cedar has no division, so these should parse-error)
        # Actually cedar has no / operator — just + - * and unary -
        # Let's test division attempt: should be parse error in both
        # Actually cedar-policy parses / as part of entity IDs not operator
        # Skip division, just test edge arithmetic
        ("q9_max_i64",     f'{MAX_I64} == {MAX_I64}'),
        ("q9_min_i64",     f'{MIN_I64} == {MIN_I64}'),
        ("q9_max_minus_1", f'{MAX_I64} - 1 == {MAX_I64 - 1}'),
        ("q9_zero_mul",    '0 * 99999 == 0'),
        ("q9_neg_mul",     '-3 * 4 == -12'),
        ("q9_neg_neg_mul", '(-3) * (-4) == 12'),
        # Mixed comparison with arithmetic
        ("q9_arith_cmp",   '(1 + 2) == (2 + 1)'),
        ("q9_nested_arith", '(1 + (2 * 3)) == 7'),
        ("q9_sub_neg",     '1 - (-1) == 2'),
    ]
    for label, expr in cases:
        out.append({
            "sample_id": label,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(expr),
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# Q10: Cedar-go specific namespace / type coercion corners
# ──────────────────────────────────────────────────────────────────

def shape_q10_type_coercion() -> list[dict[str, Any]]:
    """Patterns where Go might coerce types differently from Rust."""
    out = []
    cases = [
        # Integer vs long comparison
        ("q10_int_long",       '1 == 1'),
        ("q10_bool_not_int",   '!(1 == 2)'),
        # Set with mixed types (Cedar is untyped; both should handle)
        ("q10_set_mixed",      '[1, "two", true].contains(1)'),
        ("q10_set_mixed_str",  '[1, "two", true].contains("two")'),
        ("q10_set_mixed_bool", '[1, "two", true].contains(true)'),
        # Set operations
        ("q10_set_contains_all_empty", '[1,2,3].containsAll([])'),
        ("q10_set_contains_any_empty", '[1,2,3].containsAny([])'),
        ("q10_empty_contains_all",     '[].containsAll([])'),
        ("q10_empty_contains_any",     '[].containsAny([])'),
        ("q10_empty_is_empty",         '[].isEmpty()'),
        ("q10_nonempty_is_empty",      '[1].isEmpty()'),
        # Boolean operations
        ("q10_true_and_true",  'true && true'),
        ("q10_true_and_false", 'true && false'),
        ("q10_false_or_false", 'false || false'),
        ("q10_false_or_true",  'false || true'),
        # Comparison operators
        ("q10_lt_nums",        '1 < 2'),
        ("q10_le_nums",        '1 <= 1'),
        ("q10_gt_nums",        '2 > 1'),
        ("q10_ge_nums",        '2 >= 2'),
        # Null / missing entity attribute (should error in both)
        ("q10_attr_missing",   'principal has nonexistent_attr'),
        # Context access (we use empty context)
        ("q10_ctx_has",        'context has any_key'),
    ]
    for label, expr in cases:
        out.append({
            "sample_id": label,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(expr),
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# Q11: Deeper decimal + IP cross-exploration
# ──────────────────────────────────────────────────────────────────

def shape_q11_decimal_ip_cross() -> list[dict[str, Any]]:
    """Additional combinations probing interactions between decimal + IP parsing
    and the known B1/B2 bugs. Verifies all +sign decimal variants and zone-id
    IPv6 variants through comparison ops."""
    out = []
    # All +sign decimal variants against all 4 comparison ops
    pos_sign_vals = [
        ("+0.0", "0.0"),
        ("+0.1", "0.1"),
        ("+1.0", "1.0"),
        ("+99.9999", "99.9999"),
        ("+922337203685477.5807", "922337203685477.5807"),
    ]
    ops = ["lessThan", "lessThanOrEqual", "greaterThan", "greaterThanOrEqual"]
    for (pos, canon) in pos_sign_vals:
        for op in ops:
            label = f"q11_pos_{pos.replace('+','p').replace('.','d')}_{op}"
            expr = f'decimal("{pos}").{op}(decimal("{canon}"))'
            out.append({
                "sample_id": label,
                "principal": "User::alice",
                "action": "Action::view",
                "resource": "Document::doc1",
                "policy": _wrap(expr),
                "context": {},
            })

    # More zone-id IPv6 variants through isLoopback/isMulticast/isInRange
    zone_ips = [
        ("fe80::1%eth0", "isIpv4"),
        ("fe80::1%eth0", "isLoopback"),
        ("fe80::1%eth0", "isMulticast"),
        ("::1%lo", "isIpv6"),
        ("::1%lo", "isLoopback"),
        ("2001:db8::1%eth0", "isIpv6"),
        ("2001:db8::1%eth0", "isMulticast"),
    ]
    for (ip, op) in zone_ips:
        ip_id = ip.replace(":", "x").replace("%", "Z").replace(".", "_")
        label = f"q11_zone_{ip_id}_{op}"
        expr = f'ip("{ip}").{op}()'
        out.append({
            "sample_id": label,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(expr),
            "context": {},
        })

    # Zone-id in isInRange
    zone_inrange = [
        ("fe80::1%eth0", "fe80::/10"),
        ("fe80::1%eth0", "::/0"),
        ("::1%lo", "::1/128"),
    ]
    for (ip, rng) in zone_inrange:
        ip_id = ip.replace(":", "x").replace("%", "Z").replace(".", "_")
        rng_id = rng.replace(":", "x").replace("/", "s").replace(".", "_")
        label = f"q11_zone_{ip_id}_inrange_{rng_id}"
        expr = f'ip("{ip}").isInRange(ip("{rng}"))'
        out.append({
            "sample_id": label,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(expr),
            "context": {},
        })

    return out


# ──────────────────────────────────────────────────────────────────
# Q12: Cedar policy scope constraints
# ──────────────────────────────────────────────────────────────────

def shape_q12_scope() -> list[dict[str, Any]]:
    """Scope-level constraints in permit/forbid head (principal ==, action ==, etc.)"""
    out = []
    cases = [
        # principal scope
        ("q12_scope_principal_eq",
         'permit(principal == User::"alice", action, resource);'),
        ("q12_scope_principal_eq_miss",
         'permit(principal == User::"bob", action, resource);'),  # alice != bob
        ("q12_scope_principal_in",
         'permit(principal in Group::"users", action, resource);'),
        ("q12_scope_principal_is",
         'permit(principal is User, action, resource);'),
        # action scope
        ("q12_scope_action_eq",
         'permit(principal, action == Action::"view", resource);'),
        ("q12_scope_action_eq_miss",
         'permit(principal, action == Action::"edit", resource);'),  # action is view
        ("q12_scope_action_in",
         'permit(principal, action in [Action::"view", Action::"edit"], resource);'),
        # resource scope
        ("q12_scope_resource_eq",
         'permit(principal, action, resource == Document::"doc1");'),
        ("q12_scope_resource_eq_miss",
         'permit(principal, action, resource == Document::"doc2");'),  # resource is doc1
        ("q12_scope_resource_is",
         'permit(principal, action, resource is Document);'),
        ("q12_scope_resource_is_miss",
         'permit(principal, action, resource is Photo);'),  # resource is Document not Photo
        # Compound scope
        ("q12_scope_all_match",
         'permit(principal == User::"alice", action == Action::"view", resource == Document::"doc1");'),
        ("q12_scope_all_mismatch",
         'permit(principal == User::"alice", action == Action::"view", resource == Document::"doc2");'),
        # forbid with scope
        ("q12_forbid_scope_action",
         'permit(principal, action, resource);\nforbid(principal, action == Action::"view", resource);'),
        ("q12_forbid_scope_miss",
         'permit(principal, action, resource);\nforbid(principal, action == Action::"admin", resource);'),
    ]
    for label, policy in cases:
        out.append({
            "sample_id": label,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": policy,
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# Q13: Duration edge cases (deeper than Q3)
# ──────────────────────────────────────────────────────────────────

def shape_q13_duration_edge() -> list[dict[str, Any]]:
    """Deep duration parsing edge cases where go/rust might diverge."""
    out = []
    cases = [
        # Unit ordering (Cedar spec requires specific order)
        ("q13_dur_d_only",       'duration("1d").toSeconds() == 86400'),
        ("q13_dur_h_only",       'duration("1h").toSeconds() == 3600'),
        ("q13_dur_m_only",       'duration("1m").toSeconds() == 60'),
        ("q13_dur_s_only",       'duration("1s").toSeconds() == 1'),
        ("q13_dur_ms_only",      'duration("1ms").toMilliseconds() == 1'),
        # Combined units
        ("q13_dur_dhms",         'duration("1d2h3m4s").toSeconds() == 93784'),
        ("q13_dur_hms",          'duration("2h3m4s").toSeconds() == 7384'),
        ("q13_dur_dhm",          'duration("1d2h3m").toSeconds() == 93780'),
        # Wrong unit order (should reject? Cedar spec: d h m s ms)
        ("q13_dur_wrong_order",  'duration("1s2m").toSeconds() == 0'),
        ("q13_dur_h_before_d",   'duration("2h1d").toSeconds() == 0'),
        # Negative duration
        ("q13_dur_neg",          'duration("-1d").toSeconds() < 0'),
        ("q13_dur_neg_ms",       'duration("-500ms").toMilliseconds() < 0'),
        # Large duration
        ("q13_dur_large_d",      'duration("36500d").toSeconds() > 0'),
        # Fractional units (Cedar spec: integers only, no fractional units)
        ("q13_dur_frac_d",       'duration("1.5d").toSeconds() == 0'),
        ("q13_dur_frac_h",       'duration("1.5h").toSeconds() == 0'),
        # Zero duration
        ("q13_dur_zero_s",       'duration("0s").toSeconds() == 0'),
        ("q13_dur_zero_ms",      'duration("0ms").toMilliseconds() == 0'),
        # Overflow: very large number of days
        ("q13_dur_huge",         'duration("9999999d").toSeconds() > 0'),
        # Empty
        ("q13_dur_empty_str",    'duration("").toSeconds() == 0'),
        # Just number, no unit
        ("q13_dur_no_unit",      'duration("86400").toSeconds() == 86400'),
        # Duration compare with offset
        ("q13_dur_cmp_lt",       'duration("1h") < duration("2h")'),
        ("q13_dur_cmp_eq",       'duration("3600s") == duration("1h")'),
        ("q13_dur_cmp_ms_s",     'duration("1000ms") == duration("1s")'),
        ("q13_dur_toMs_1d",      'duration("1d").toMilliseconds() == 86400000'),
    ]
    for label, expr in cases:
        out.append({
            "sample_id": label,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": _wrap(expr),
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# Aggregate
# ──────────────────────────────────────────────────────────────────

ALL_SHAPES_V2: dict[str, list[dict[str, Any]]] = {
    "q1_decimal_boundary":   shape_q1_decimal_boundary(),
    "q2_ip_extra":           shape_q2_ip_extra(),
    "q3_datetime_ops":       shape_q3_datetime_ops(),
    "q4_string_ops":         shape_q4_string_ops(),
    "q5_precedence":         shape_q5_precedence(),
    "q6_entity_hierarchy":   shape_q6_entity_hierarchy(),
    "q7_records":            shape_q7_records(),
    "q8_multi_policy":       shape_q8_multi_policy(),
    "q9_arithmetic":         shape_q9_arithmetic(),
    "q10_type_coercion":     shape_q10_type_coercion(),
    "q11_decimal_ip_cross":  shape_q11_decimal_ip_cross(),
    "q12_scope":             shape_q12_scope(),
    "q13_duration_edge":     shape_q13_duration_edge(),
}


def all_tuples_v2() -> list[dict[str, Any]]:
    out = []
    for shape, tups in ALL_SHAPES_V2.items():
        for t in tups:
            t = dict(t)
            t["shape"] = shape
            t["idx"] = f"{shape}__{t['sample_id']}"
            out.append(t)
    return out


if __name__ == "__main__":
    import json
    import sys
    tups = all_tuples_v2()
    print(f"Total tuples: {len(tups)}", file=sys.stderr)
    for shape in ALL_SHAPES_V2:
        print(f"  {shape}: {len(ALL_SHAPES_V2[shape])}", file=sys.stderr)
    if "--dump" in sys.argv:
        for t in tups:
            print(json.dumps(t))
