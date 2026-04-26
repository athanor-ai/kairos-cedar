"""
Widened shapes for the §8 diff hunt  - bug-hunt-2026-04-25.

Each shape is a (shape_id, list[Tuple]) pair where Tuple = dict with keys:
  - sample_id: str (unique within shape)
  - principal, action, resource: "Type::eid"
  - policy: full Cedar policy text (single statement, semicolon-terminated)
  - context: dict (will be passed to runners; default {})

Shapes are grouped by widening priority:
  P1  - decimal extension drift
  P2  - ipaddr edge cases
  P3  - datetime parse drift   (cedar-go has datetime; cedar-policy may not enable it without --features)
  P4  - Unicode strings on `like`
  P5  - set operations at large N
  P6  - short-circuit-order divergence in nested && / ||
  P7  - AWS IAM-style layered policies
  P8  - RBAC document-share

Note on entity / schema decisions:
  • All shapes use the SAME fixed schema + entities as the V1 generator
    so we don't shift load to schema differences. Decimals/ips/etc. live
    inside *condition* expressions so we don't need new attribute types.
  • Where an attribute IS required (e.g. `principal.region == ip("...")`
    style), we attach it via a per-shape entities override.
"""

from __future__ import annotations

import itertools
from typing import Any


def _wrap(policy_body: str, idx: int, label: str) -> str:
    """Wrap a condition expression in a permit-when policy."""
    return f'permit(principal, action, resource) when {{ {policy_body} }};'


# ──────────────────────────────────────────────────────────────────
# P1: decimal extension drift
# ──────────────────────────────────────────────────────────────────

# Cedar decimal grammar: 4-digit fractional precision max, value range
# −922337203685477.5808 to 922337203685477.5807. Operators: lessThan,
# lessThanOrEqual, greaterThan, greaterThanOrEqual.

DECIMAL_EDGE_LITERALS = [
    # canonical
    ("d_canonical", '0.1'),
    ("d_zero", '0.0'),
    ("d_neg_zero", '-0.0'),
    ("d_max_int_part", '922337203685477.5807'),
    ("d_min_int_part", '-922337203685477.5808'),
    # non-canonical: trailing zeros
    ("d_trailing_z2", '0.10'),
    ("d_trailing_z3", '0.100'),
    ("d_trailing_z4", '0.1000'),
    ("d_trailing_z_neg", '-0.10'),
    # leading zeros in int part
    ("d_lead_zero_int", '01.5'),
    ("d_lead_zero_int_2", '007.0'),
    # leading zeros in frac (legitimate)
    ("d_lead_zero_frac", '1.0001'),
    # over-precision (>4 digits)
    ("d_over_prec_5", '0.12345'),
    ("d_over_prec_8", '0.12345678'),
    # missing decimal point  (cedar-go requires it; Rust may auto-coerce)
    ("d_no_dot", '1'),
    ("d_no_dot_neg", '-7'),
    # explicit + sign on int part
    ("d_pos_sign", '+1.5'),
    ("d_pos_sign_zero", '+0.0'),
    # explicit + sign in frac (only Go's ParseUint accepts '+')
    ("d_frac_plus", '1.+5'),
    # whitespace
    ("d_lead_space", ' 1.5'),
    ("d_trail_space", '1.5 '),
    # empty fractional
    ("d_empty_frac", '1.'),
    # only fractional
    ("d_only_frac", '.5'),
    # multiple dots
    ("d_two_dots", '1.5.0'),
    # arithmetic-overflow boundary (just-over)
    ("d_just_over_max", '922337203685477.5808'),
    ("d_just_under_min", '-922337203685477.5809'),
    # large exponent forms (not legal in Cedar grammar  - must reject)
    ("d_exp_form", '1e2'),
    ("d_exp_form_caps", '1E2'),
    # negative zero variations
    ("d_neg_zero_4", '-0.0000'),
    # 5+ digit overflow at frac with leading zeros
    ("d_frac_lead_zero_over", '0.00001'),
]

DECIMAL_OPS = ["lessThan", "lessThanOrEqual", "greaterThan", "greaterThanOrEqual"]


def shape_p1_decimal_parse() -> list[dict[str, Any]]:
    """Each tuple: principal == User::"alice" && decimal("X").lessThan(decimal("0.5"))
    where X varies through DECIMAL_EDGE_LITERALS. Both runners must AGREE on
    accept/reject; if one accepts and other rejects, that's a divergence."""
    out = []
    for (lit_id, lit) in DECIMAL_EDGE_LITERALS:
        body = (
            f'principal == User::"alice" && '
            f'decimal("{lit}").lessThan(decimal("0.5"))'
        )
        # escape any " in lit so Cedar parses; for our literals there are none
        out.append({
            "sample_id": f"p1_parse_{lit_id}",
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": f'permit(principal, action, resource) when {{ {body} }};',
            "context": {},
        })
    return out


def shape_p1_decimal_compare() -> list[dict[str, Any]]:
    """Pairwise compare (lessThan / lessThanOrEqual / greaterThan / greaterThanOrEqual)
    on canonical decimals across the value range. We want both runners to agree."""
    out = []
    pairs = [
        ('0.1', '0.10'),       # equality despite trailing zero
        ('0.10', '0.100'),     # 2 vs 3 trailing zeros
        ('0.0', '-0.0'),       # zero / negative zero
        ('0.0', '0.0001'),     # smallest positive
        ('922337203685477.5807', '-922337203685477.5808'),  # extremes
        ('1.0001', '1.0002'),
        ('-0.0001', '0.0001'),
        ('1.0', '1.00'),
    ]
    for i, (a, b) in enumerate(pairs):
        for op in DECIMAL_OPS:
            body = f'decimal("{a}").{op}(decimal("{b}"))'
            out.append({
                "sample_id": f"p1_cmp_{i}_{op}",
                "principal": "User::alice",
                "action": "Action::view",
                "resource": "Document::doc1",
                "policy": f'permit(principal, action, resource) when {{ {body} }};',
                "context": {},
            })
    return out


# ──────────────────────────────────────────────────────────────────
# P2: ipaddr edge cases
# ──────────────────────────────────────────────────────────────────

IP_EDGE_LITERALS = [
    # canonical
    ("ip_v4", "127.0.0.1"),
    ("ip_v6_loop", "::1"),
    ("ip_v6_loop_full", "0:0:0:0:0:0:0:1"),
    ("ip_v4_zero", "0.0.0.0"),
    ("ip_v4_bcast", "255.255.255.255"),
    # IPv4 leading zeros (Go netip rejects since 1.17? Rust?)
    ("ip_v4_lead_zero", "127.000.000.001"),
    ("ip_v4_lead_zero_2", "010.0.0.1"),
    # IPv4-mapped IPv6
    ("ip_v4_mapped", "::ffff:192.0.2.1"),
    ("ip_v4_mapped_compat", "::192.0.2.1"),
    # zone-id IPv6
    ("ip_v6_zone", "fe80::1%eth0"),
    # prefix CIDR
    ("ip_v4_prefix", "10.0.0.0/8"),
    ("ip_v6_prefix", "2001:db8::/32"),
    ("ip_v4_prefix_full", "10.0.0.0/32"),
    # zero-prefix
    ("ip_zero_prefix", "0.0.0.0/0"),
    ("ip_v6_zero_prefix", "::/0"),
    # host bits set in CIDR (some parsers normalize, some reject)
    ("ip_host_bits", "10.0.0.5/8"),
    # leading zeros in IPv6
    ("ip_v6_lead_zero_compress", "2001:0db8:0000:0000:0000:0000:0000:0001"),
    # uppercase IPv6
    ("ip_v6_upper", "2001:DB8::1"),
    # mixed case
    ("ip_v6_mixed_case", "2001:Db8::1"),
    # invalid  - must both reject
    ("ip_v4_too_big", "256.0.0.1"),
    ("ip_v4_three_octets", "192.168.1"),
    ("ip_empty", ""),
    # whitespace
    ("ip_lead_space", " 127.0.0.1"),
    # multicast / loopback markers
    ("ip_v4_multicast", "224.0.0.1"),
    ("ip_v6_multicast", "ff02::1"),
    # link-local
    ("ip_v6_linklocal", "fe80::1"),
    # zero-compression edge
    ("ip_v6_double_compress", "::"),
    ("ip_v6_two_zeros", "::0"),
]

IP_OPS = ["isIpv4", "isIpv6", "isLoopback", "isMulticast"]


def shape_p2_ip_parse() -> list[dict[str, Any]]:
    """ip("X").isIpv4()  - fundamental drift question is whether parse succeeds."""
    out = []
    for (lit_id, lit) in IP_EDGE_LITERALS:
        # quote the literal carefully
        if '"' in lit:
            continue  # skip if it would corrupt our policy text
        body = f'ip("{lit}").isIpv4()'
        out.append({
            "sample_id": f"p2_parse_{lit_id}",
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": f'permit(principal, action, resource) when {{ {body} }};',
            "context": {},
        })
    return out


def shape_p2_ip_ops() -> list[dict[str, Any]]:
    """All 4 ops × all canonical-pass IPs  - divergence on op semantics is rare but valued."""
    out = []
    canon_ips = [
        "127.0.0.1", "::1", "0.0.0.0", "10.0.0.0/8", "fe80::1%eth0",
        "224.0.0.1", "ff02::1", "::ffff:192.0.2.1",
    ]
    for ip in canon_ips:
        ip_id = ip.replace(".", "_").replace(":", "x").replace("/", "_s_").replace("%", "_p_")
        for op in IP_OPS:
            body = f'ip("{ip}").{op}()'
            out.append({
                "sample_id": f"p2_op_{ip_id}_{op}",
                "principal": "User::alice",
                "action": "Action::view",
                "resource": "Document::doc1",
                "policy": f'permit(principal, action, resource) when {{ {body} }};',
                "context": {},
            })
    return out


def shape_p2_ip_in_range() -> list[dict[str, Any]]:
    """isInRange  - semantic disagreement is paper-grade."""
    out = []
    pairs = [
        ("127.0.0.1", "127.0.0.0/8"),
        ("10.0.0.5", "10.0.0.0/8"),
        ("10.0.0.5", "10.0.0.0/24"),
        ("10.255.255.255", "10.0.0.0/8"),
        ("11.0.0.0", "10.0.0.0/8"),       # outside
        ("::1", "::/0"),
        ("::1", "::1/128"),
        ("2001:db8::1", "2001:db8::/32"),
        ("2001:db9::1", "2001:db8::/32"),  # outside
        ("::ffff:127.0.0.1", "127.0.0.0/8"),  # ipv4-mapped vs ipv4 prefix
    ]
    for i, (ip, rng) in enumerate(pairs):
        body = f'ip("{ip}").isInRange(ip("{rng}"))'
        out.append({
            "sample_id": f"p2_inrange_{i}",
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": f'permit(principal, action, resource) when {{ {body} }};',
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# P3: datetime parse drift
# ──────────────────────────────────────────────────────────────────

# cedar-go has datetime as a built-in extension. cedar-policy 4.10 has it
# behind --extension-functions; in 4.x default build it is enabled.

DATETIME_LITERALS = [
    # canonical
    ("dt_basic", "2025-04-25T00:00:00Z"),
    # fractional seconds  - Cedar spec only allows 3-digit (millisecond)
    ("dt_ms_3", "2025-04-25T00:00:00.123Z"),
    ("dt_ms_1", "2025-04-25T00:00:00.1Z"),
    ("dt_ms_2", "2025-04-25T00:00:00.12Z"),
    ("dt_ms_4", "2025-04-25T00:00:00.1234Z"),
    ("dt_ms_6", "2025-04-25T00:00:00.123456Z"),
    ("dt_ms_9", "2025-04-25T00:00:00.123456789Z"),
    # offset forms
    ("dt_offset_z", "2025-04-25T00:00:00Z"),
    ("dt_offset_p0000", "2025-04-25T00:00:00+0000"),
    ("dt_offset_p0_0", "2025-04-25T00:00:00+00:00"),
    ("dt_offset_n0500", "2025-04-25T00:00:00-0500"),
    ("dt_offset_n05_00", "2025-04-25T00:00:00-05:00"),
    # leap second (cedar should reject  - no 60)
    ("dt_leap", "2016-12-31T23:59:60Z"),
    # pre-epoch
    ("dt_pre_epoch", "1969-12-31T23:59:59Z"),
    ("dt_year_1", "0001-01-01T00:00:00Z"),
    # far future > 2038
    ("dt_year_2099", "2099-12-31T23:59:59Z"),
    ("dt_year_3000", "3000-01-01T00:00:00Z"),
    # date-only (no T component)
    ("dt_date_only", "2025-04-25"),
    # negative year
    ("dt_neg_year", "-0001-01-01T00:00:00Z"),
    # just whitespace
    ("dt_lead_space", " 2025-04-25T00:00:00Z"),
    # duration-style mistake
    ("dt_iso_dur", "P1D"),
]


def shape_p3_datetime_parse() -> list[dict[str, Any]]:
    out = []
    for (lit_id, lit) in DATETIME_LITERALS:
        if '"' in lit:
            continue
        body = f'datetime("{lit}") < datetime("2030-01-01T00:00:00Z")'
        out.append({
            "sample_id": f"p3_dt_{lit_id}",
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": f'permit(principal, action, resource) when {{ {body} }};',
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# P4: Unicode strings on `like`
# ──────────────────────────────────────────────────────────────────

UNICODE_PAIRS = [
    # (string-literal, like-pattern, label)
    ("café", "café", "u_basic"),
    # NFC vs NFD: U+00E9 (precomposed) vs U+0065 U+0301 (e + combining acute)
    ("café", "café", "u_nfd_pattern_nfc_str"),
    ("café", "café", "u_nfc_pattern_nfd_str"),
    # surrogate pair (4-byte UTF-8)
    ("\U0001F600", "*", "u_emoji_star"),
    ("\U0001F600", "\U0001F600", "u_emoji_exact"),
    # BOM-prefixed
    ("﻿foo", "foo", "u_bom_str"),
    ("foo", "﻿foo", "u_bom_pat"),
    # backslash + special star
    ("a*b", "a\\*b", "u_escape_star"),
    ("a\\b", "a\\\\b", "u_escape_backslash"),
    # zero-width joiner
    ("a‍z", "az", "u_zwj"),
    # Empty string
    ("", "", "u_empty"),
    ("", "*", "u_empty_star"),
    ("foo", "", "u_str_empty_pat"),
    # large unicode scalar
    ("\U0010FFFF", "*", "u_max_scalar"),
    # right-to-left embedded
    ("a‮b", "a*b", "u_rtl"),
    # combining tilde on n
    ("niño", "niño", "u_tilde_nfc_pat_nfd"),
]


def _python_to_cedar_str(s: str) -> str:
    """Render a Python string as a Cedar string literal (escape ", \\, \\n, \\t).
    Cedar string literals support \\u{XXXX} for unicode."""
    out = []
    for ch in s:
        cp = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == '\\':
            out.append('\\\\')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\t':
            out.append('\\t')
        elif ch == '\r':
            out.append('\\r')
        elif 0x20 <= cp <= 0x7E:
            out.append(ch)
        else:
            out.append(f'\\u{{{cp:X}}}')
    return ''.join(out)


def shape_p4_unicode_like() -> list[dict[str, Any]]:
    out = []
    for (s, pat, label) in UNICODE_PAIRS:
        s_lit = _python_to_cedar_str(s)
        # pattern: in Cedar, only `*` and `\*` are special; backslash is also escaped
        pat_lit = _python_to_cedar_str(pat)
        body = f'"{s_lit}" like "{pat_lit}"'
        out.append({
            "sample_id": f"p4_{label}",
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": f'permit(principal, action, resource) when {{ {body} }};',
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# P5: set operations at large N
# ──────────────────────────────────────────────────────────────────

def shape_p5_set_ops() -> list[dict[str, Any]]:
    out = []
    # different sizes, pre-built literal sets
    for n in [10, 100, 500]:
        # contains-all where right is a subset of left
        elems_left = "[" + ",".join(str(i) for i in range(n)) + "]"
        elems_right = "[" + ",".join(str(i) for i in range(n // 2)) + "]"
        body = f'{elems_left}.containsAll({elems_right})'
        out.append({
            "sample_id": f"p5_containsAll_n{n}",
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": f'permit(principal, action, resource) when {{ {body} }};',
            "context": {},
        })
        # containsAny with empty right
        body2 = f'{elems_left}.containsAny([])'
        out.append({
            "sample_id": f"p5_containsAny_empty_n{n}",
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": f'permit(principal, action, resource) when {{ {body2} }};',
            "context": {},
        })
        # isEmpty on non-empty large set
        body3 = f'{elems_left}.isEmpty()'
        out.append({
            "sample_id": f"p5_isEmpty_n{n}",
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": f'permit(principal, action, resource) when {{ {body3} }};',
            "context": {},
        })
    # order-dependent set construction (Cedar sets are unordered, so [1,2] == [2,1])
    body = '[1,2,3].containsAll([3,2,1])'
    out.append({
        "sample_id": "p5_order_invariance",
        "principal": "User::alice",
        "action": "Action::view",
        "resource": "Document::doc1",
        "policy": f'permit(principal, action, resource) when {{ {body} }};',
        "context": {},
    })
    # nested sets
    body = '[[1,2],[3,4]].contains([1,2])'
    out.append({
        "sample_id": "p5_nested_set",
        "principal": "User::alice",
        "action": "Action::view",
        "resource": "Document::doc1",
        "policy": f'permit(principal, action, resource) when {{ {body} }};',
        "context": {},
    })
    return out


# ──────────────────────────────────────────────────────────────────
# P6: short-circuit-order divergence in nested && / ||
# ──────────────────────────────────────────────────────────────────

# Cedar `&&` and `||` are short-circuit. Both Rust and Go say they short-circuit
# left-to-right. Combine ext-type errors with `&&` to test that:
# decimal("garbage") will throw; with `false && decimal("garbage").lessThan(...)`,
# short-circuit means false ⇒ false (no error). With `true && decimal("garbage")...`
# the error propagates ⇒ Deny. Drift = one short-circuits, the other doesn't.

def shape_p6_short_circuit() -> list[dict[str, Any]]:
    out = []
    # bad-decimal (over-precision)  - known to error in Go.
    bad_dec = '0.12345'
    bad_ip = '256.0.0.1'

    cases = [
        # (label, expr)
        ("p6_falseAnd_bad_dec",     f'false && decimal("{bad_dec}").lessThan(decimal("0.5"))'),
        ("p6_trueOr_bad_dec",       f'true  || decimal("{bad_dec}").lessThan(decimal("0.5"))'),
        ("p6_trueAnd_bad_dec",      f'true  && decimal("{bad_dec}").lessThan(decimal("0.5"))'),
        ("p6_falseOr_bad_dec",      f'false || decimal("{bad_dec}").lessThan(decimal("0.5"))'),
        ("p6_falseAnd_bad_ip",      f'false && ip("{bad_ip}").isIpv4()'),
        ("p6_trueOr_bad_ip",        f'true  || ip("{bad_ip}").isIpv4()'),
        # nested
        ("p6_nested_short",         f'(false && decimal("{bad_dec}").lessThan(decimal("0.5"))) || (1 == 1)'),
        # double-deep nested
        ("p6_double_nested_F_F",    f'false && (false && decimal("{bad_dec}").lessThan(decimal("0.5")))'),
        ("p6_double_nested_T_F",    f'true  && (false && decimal("{bad_dec}").lessThan(decimal("0.5")))'),
        ("p6_double_nested_F_T",    f'false || (true  || decimal("{bad_dec}").lessThan(decimal("0.5")))'),
        # ITE with bad branch  - Cedar `if` short-circuits unselected branch
        ("p6_ite_unselected_bad",   f'if true then 1 == 1 else (decimal("{bad_dec}").lessThan(decimal("0.5")))'),
        ("p6_ite_unselected_bad_2", f'if false then (decimal("{bad_dec}").lessThan(decimal("0.5"))) else 1 == 1'),
    ]
    for label, expr in cases:
        out.append({
            "sample_id": label,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": f'permit(principal, action, resource) when {{ {expr} }};',
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# P7: AWS IAM-style multi-policy + hierarchies
# ──────────────────────────────────────────────────────────────────

# Single-policy tuples only (our harness invokes per-tuple). Use compound
# conditions to layer permit/forbid effects.

def shape_p7_iam_layered() -> list[dict[str, Any]]:
    out = []
    cases = [
        ("p7_iam_principal_eq_and_resource_in",
         'permit(principal == User::"alice", action, resource in Document::"doc1") '
         'when { action == Action::"view" || action == Action::"edit" };'),
        ("p7_iam_admin_full_access",
         'permit(principal in Group::"admins", action, resource);'),
        ("p7_iam_unless_action_admin",
         'permit(principal, action, resource) unless { action == Action::"admin" };'),
        ("p7_iam_layered_when_unless",
         'permit(principal, action, resource) '
         'when { principal is User } '
         'unless { resource == Document::"doc2" };'),
        ("p7_iam_principal_in_unless_admin",
         'permit(principal, action, resource) '
         'when { principal in Group::"users" } '
         'unless { action == Action::"admin" };'),
        ("p7_iam_complex_cond",
         'permit(principal, action, resource) when { '
         '(principal == User::"alice" && action == Action::"view") || '
         '(principal == User::"bob" && resource is Document) };'),
        ("p7_iam_nested_is_in",
         'permit(principal, action, resource) when { '
         'principal is User && resource is Document && action == Action::"view" };'),
        ("p7_iam_forbid_with_when",
         'forbid(principal, action, resource) when { '
         'action == Action::"admin" && !(principal in Group::"admins") };'),
    ]
    for (sid, policy) in cases:
        out.append({
            "sample_id": sid,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": policy,
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# P8: RBAC document-share style policies
# ──────────────────────────────────────────────────────────────────

def shape_p8_rbac_docshare() -> list[dict[str, Any]]:
    out = []
    cases = [
        ("p8_rbac_owner_only",
         'permit(principal, action, resource) when { '
         'principal == User::"alice" && resource == Document::"doc1" };'),
        ("p8_rbac_view_for_anyone",
         'permit(principal, action == Action::"view", resource is Document);'),
        ("p8_rbac_edit_for_admins",
         'permit(principal in Group::"admins", action in [Action::"edit", Action::"admin"], resource);'),
        ("p8_rbac_chained_in",
         'permit(principal, action, resource) when { '
         'principal in Group::"users" || principal in Group::"admins" };'),
        ("p8_rbac_double_negation",
         'permit(principal, action, resource) when { '
         '!(!(principal is User)) };'),
        ("p8_rbac_long_or",
         'permit(principal, action, resource) when { '
         'action == Action::"view" || action == Action::"edit" || action == Action::"admin" };'),
    ]
    for (sid, policy) in cases:
        out.append({
            "sample_id": sid,
            "principal": "User::alice",
            "action": "Action::view",
            "resource": "Document::doc1",
            "policy": policy,
            "context": {},
        })
    return out


# ──────────────────────────────────────────────────────────────────
# Aggregate
# ──────────────────────────────────────────────────────────────────

ALL_SHAPES: dict[str, list[dict[str, Any]]] = {
    "p1_decimal_parse":       shape_p1_decimal_parse(),
    "p1_decimal_compare":     shape_p1_decimal_compare(),
    "p2_ip_parse":            shape_p2_ip_parse(),
    "p2_ip_ops":              shape_p2_ip_ops(),
    "p2_ip_in_range":         shape_p2_ip_in_range(),
    "p3_datetime_parse":      shape_p3_datetime_parse(),
    "p4_unicode_like":        shape_p4_unicode_like(),
    "p5_set_ops":             shape_p5_set_ops(),
    "p6_short_circuit":       shape_p6_short_circuit(),
    "p7_iam_layered":         shape_p7_iam_layered(),
    "p8_rbac_docshare":       shape_p8_rbac_docshare(),
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
