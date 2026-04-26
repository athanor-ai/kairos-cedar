"""
probe_inputs.py — generator of JSON policy probe inputs for round-trip testing.

Cedar JSON policy format reference:
  https://docs.cedarpolicy.com/policies/json-format.html

Each probe is a dict with:
  id          — unique string identifying this probe
  policy_json — a dict (will be JSON-encoded) representing a Cedar policy

Probe categories:
  A. CONFORMANT — well-formed per spec; round-trip should be identity or at least non-panicky
  B. EDGE_ZERO  — empty-arg arrays for extension method calls (the NEW-2 class)
  C. MALFORMED  — wrong types, missing required fields (parse_fail expected, not a bug)
  D. EXTRAS     — extra fields in objects (should be ignored or fail gracefully)

Usage:
  python3 probe_inputs.py > probes.ndjson   (NDJSON for the Go harness)
  python3 probe_inputs.py --list-ids        (just print IDs)
"""

import json
import sys

# ── Helpers ───────────────────────────────────────────────────────────────────

def scope_all():
    return {"op": "All"}

def scope_eq(etype, eid):
    return {"op": "==", "entity": {"type": etype, "id": eid}}

def scope_in(etype, eid):
    return {"op": "in", "entity": {"type": etype, "id": eid}}

def scope_is(etype):
    return {"op": "is", "entity_type": etype}

def scope_is_in(etype, etype2, eid2):
    return {"op": "is", "entity_type": etype, "in": {"entity": {"type": etype2, "id": eid2}}}

def condition_when(body):
    return {"kind": "when", "body": body}

def condition_unless(body):
    return {"kind": "unless", "body": body}

def principal():
    return {"Var": "principal"}

def action():
    return {"Var": "action"}

def resource():
    return {"Var": "resource"}

def context():
    return {"Var": "context"}

def value(v):
    return {"Value": v}

def binary(op, left, right):
    return {op: {"left": left, "right": right}}

def unary(op, arg):
    return {op: {"arg": arg}}

def ext_call(name, *args):
    """Extension call — args is the list of arg nodes (JSON-expressible)."""
    return {name: list(args)}

def if_then_else(cond, then, else_):
    return {"if-then-else": {"if": cond, "then": then, "else": else_}}

def set_node(*elems):
    return {"Set": list(elems)}

def record_node(**kwargs):
    return {"Record": {k: v for k, v in kwargs.items()}}

def has_attr(left, attr):
    return {"has": {"left": left, "attr": attr}}

def access_attr(left, attr):
    return {".": {"left": left, "attr": attr}}

def like_node(left, pattern):
    return {"like": {"left": left, "pattern": pattern}}

def is_node(left, entity_type, in_=None):
    n = {"is": {"left": left, "entity_type": entity_type}}
    if in_ is not None:
        n["is"]["in"] = in_
    return n

def base_policy(effect, conditions=None, **scope):
    """
    Minimal valid policy skeleton.
    scope: principal=..., action=..., resource=... override
    """
    p = {
        "effect": effect,
        "principal": scope.get("principal", scope_all()),
        "action": scope.get("action", scope_all()),
        "resource": scope.get("resource", scope_all()),
    }
    if conditions:
        p["conditions"] = conditions
    return p


# ── Probe catalogue ───────────────────────────────────────────────────────────

PROBES = []


def probe(id_, policy, category, note=""):
    PROBES.append({"id": id_, "policy_json": policy, "category": category, "note": note})


# ── A: CONFORMANT probes ──────────────────────────────────────────────────────

# A-001: simplest permit-all
probe("A-001-permit-all", base_policy("permit"), "conformant", "bare permit all")

# A-002: forbid-all
probe("A-002-forbid-all", base_policy("forbid"), "conformant", "bare forbid all")

# A-003: equality scope
probe("A-003-scope-eq", base_policy(
    "permit",
    principal=scope_eq("User", "alice"),
    action=scope_eq("Action", "view"),
    resource=scope_eq("Folder", "readme"),
), "conformant")

# A-004: in scope
probe("A-004-scope-in", base_policy(
    "permit",
    principal=scope_in("User", "alice"),
    action=scope_all(),
    resource=scope_in("Folder", "public"),
), "conformant")

# A-005: is scope
probe("A-005-scope-is", base_policy(
    "permit",
    principal=scope_is("Employee"),
    action=scope_all(),
    resource=scope_all(),
), "conformant")

# A-006: is-in scope
probe("A-006-scope-is-in", base_policy(
    "permit",
    principal=scope_is_in("Employee", "Org", "acme"),
    action=scope_all(),
    resource=scope_all(),
), "conformant")

# A-007: when condition — simple equality
probe("A-007-when-eq", base_policy(
    "permit",
    conditions=[condition_when(
        binary("==", principal(), value("admin"))
    )],
), "conformant")

# A-008: when condition — binary operators
for op in ["==", "!=", "<", "<=", ">", ">="]:
    safe_op = op.replace("<", "lt").replace(">", "gt").replace("=", "e").replace("!", "ne")
    probe(
        f"A-008-binop-{safe_op}",
        base_policy("permit", conditions=[condition_when(
            binary(op, value(1), value(2))
        )]),
        "conformant",
        f"binary op {op}"
    )

# A-009: logical operators
probe("A-009-and", base_policy("permit", conditions=[condition_when(
    binary("&&", value(True), value(True))
)]), "conformant")

probe("A-010-or", base_policy("permit", conditions=[condition_when(
    binary("||", value(False), value(False))
)]), "conformant")

probe("A-011-not", base_policy("permit", conditions=[condition_when(
    unary("!", value(False))
)]), "conformant")

# A-012: arithmetic
probe("A-012-add", base_policy("permit", conditions=[condition_when(
    binary("+", value(1), value(2))
)]), "conformant")

probe("A-013-subtract", base_policy("permit", conditions=[condition_when(
    binary("-", value(5), value(3))
)]), "conformant")

probe("A-014-multiply", base_policy("permit", conditions=[condition_when(
    binary("*", value(2), value(3))
)]), "conformant")

probe("A-015-negate", base_policy("permit", conditions=[condition_when(
    unary("neg", value(5))
)]), "conformant")

# A-016: if-then-else
probe("A-016-ite", base_policy("permit", conditions=[condition_when(
    if_then_else(value(True), value(1), value(2))
)]), "conformant")

# A-017: set literal
probe("A-017-set", base_policy("permit", conditions=[condition_when(
    binary("==", set_node(value(1), value(2), value(3)), set_node(value(1), value(2), value(3)))
)]), "conformant")

# A-018: empty set
probe("A-018-empty-set", base_policy("permit", conditions=[condition_when(
    binary("==", set_node(), set_node())
)]), "conformant")

# A-019: record literal
probe("A-019-record", base_policy("permit", conditions=[condition_when(
    binary("==", record_node(x=value(1), y=value(2)), record_node(x=value(1), y=value(2)))
)]), "conformant")

# A-020: empty record
probe("A-020-empty-record", base_policy("permit", conditions=[condition_when(
    binary("==", {"Record": {}}, {"Record": {}})
)]), "conformant")

# A-021: has attribute
probe("A-021-has", base_policy("permit", conditions=[condition_when(
    has_attr(principal(), "name")
)]), "conformant")

# A-022: access attribute
probe("A-022-access", base_policy("permit", conditions=[condition_when(
    binary("==", access_attr(principal(), "name"), value("alice"))
)]), "conformant")

# A-023: like
probe("A-023-like", base_policy("permit", conditions=[condition_when(
    like_node(value("hello world"), "hello*")
)]), "conformant")

# A-024: is expression
probe("A-024-is", base_policy("permit", conditions=[condition_when(
    is_node(principal(), "Employee")
)]), "conformant")

# A-025: is-in expression
probe("A-025-is-in-expr", base_policy("permit", conditions=[condition_when(
    is_node(principal(), "Employee",
            in_=binary("==", resource(), resource()))
)]), "conformant", "is with in expression — note: in field should be a node")

# Correct is-in: in field is a node expression not a binary
probe("A-025b-is-in-expr", base_policy("permit", conditions=[condition_when(
    {"is": {"left": principal(), "entity_type": "Employee", "in": value({"type": "Org", "id": "acme"})}}
)]), "conformant")

# A-026: contains
probe("A-026-contains", base_policy("permit", conditions=[condition_when(
    binary("contains", set_node(value(1), value(2)), value(1))
)]), "conformant")

# A-027: containsAll
probe("A-027-containsAll", base_policy("permit", conditions=[condition_when(
    binary("containsAll", set_node(value(1), value(2)), set_node(value(1)))
)]), "conformant")

# A-028: containsAny
probe("A-028-containsAny", base_policy("permit", conditions=[condition_when(
    binary("containsAny", set_node(value(1), value(2)), set_node(value(3)))
)]), "conformant")

# A-029: isEmpty (unary, takes the receiver as "arg")
probe("A-029-isEmpty", base_policy("permit", conditions=[condition_when(
    {"isEmpty": {"arg": set_node()}}
)]), "conformant")

# A-030: getTag / hasTag
probe("A-030-hasTag", base_policy("permit", conditions=[condition_when(
    binary("hasTag", principal(), value("sensitivity"))
)]), "conformant")

probe("A-031-getTag", base_policy("permit", conditions=[condition_when(
    binary("getTag", principal(), value("sensitivity"))
)]), "conformant")

# A-032: in expression (binary)
probe("A-032-in-expr", base_policy("permit", conditions=[condition_when(
    binary("in", principal(), set_node(value({"type": "Group", "id": "admins"})))
)]), "conformant")

# A-033: annotations
probe("A-033-annotations", {
    "effect": "permit",
    "principal": scope_all(),
    "action": scope_all(),
    "resource": scope_all(),
    "annotations": {"advice": "allow", "id": "policy-1"},
    "conditions": [condition_when(value(True))],
}, "conformant")

# A-034: unless condition
probe("A-034-unless", base_policy("forbid", conditions=[condition_unless(
    value(True)
)]), "conformant")

# ── Extension functions (conformant, correct arity) ──────────────────────────

# ip constructor: ip("192.168.1.1")
probe("A-035-ip-constructor", base_policy("permit", conditions=[condition_when(
    binary("==", ext_call("ip", value("192.168.1.1")), ext_call("ip", value("192.168.1.1")))
)]), "conformant")

# decimal constructor
probe("A-036-decimal-constructor", base_policy("permit", conditions=[condition_when(
    binary("==", ext_call("decimal", value("1.23")), ext_call("decimal", value("1.23")))
)]), "conformant")

# datetime constructor
probe("A-037-datetime-constructor", base_policy("permit", conditions=[condition_when(
    binary("==", ext_call("datetime", value("2024-01-01T00:00:00Z")),
               ext_call("datetime", value("2024-01-01T00:00:00Z")))
)]), "conformant")

# duration constructor
probe("A-038-duration-constructor", base_policy("permit", conditions=[condition_when(
    binary("==", ext_call("duration", value("1h")), ext_call("duration", value("1h")))
)]), "conformant")

# Method-style: isIpv4(receiver)  — receiver is FIRST element of the args array in JSON
# JSON: {"isIpv4": [receiver_node]}
probe("A-039-isIpv4", base_policy("permit", conditions=[condition_when(
    ext_call("isIpv4", ext_call("ip", value("192.168.1.1")))
)]), "conformant", "isIpv4 method call: receiver is args[0]")

probe("A-040-isIpv6", base_policy("permit", conditions=[condition_when(
    ext_call("isIpv6", ext_call("ip", value("::1")))
)]), "conformant")

probe("A-041-isLoopback", base_policy("permit", conditions=[condition_when(
    ext_call("isLoopback", ext_call("ip", value("127.0.0.1")))
)]), "conformant")

probe("A-042-isMulticast", base_policy("permit", conditions=[condition_when(
    ext_call("isMulticast", ext_call("ip", value("224.0.0.1")))
)]), "conformant")

# isInRange: 2-arg method [receiver, arg]
probe("A-043-isInRange", base_policy("permit", conditions=[condition_when(
    ext_call("isInRange",
             ext_call("ip", value("192.168.1.5")),
             ext_call("ip", value("192.168.1.0/24")))
)]), "conformant")

# lessThan/greaterThan for decimal: [receiver, arg]
probe("A-044-lessThan-decimal", base_policy("permit", conditions=[condition_when(
    ext_call("lessThan",
             ext_call("decimal", value("1.0")),
             ext_call("decimal", value("2.0")))
)]), "conformant")

probe("A-045-lessThanOrEqual-decimal", base_policy("permit", conditions=[condition_when(
    ext_call("lessThanOrEqual",
             ext_call("decimal", value("1.0")),
             ext_call("decimal", value("1.0")))
)]), "conformant")

probe("A-046-greaterThan-decimal", base_policy("permit", conditions=[condition_when(
    ext_call("greaterThan",
             ext_call("decimal", value("2.0")),
             ext_call("decimal", value("1.0")))
)]), "conformant")

probe("A-047-greaterThanOrEqual-decimal", base_policy("permit", conditions=[condition_when(
    ext_call("greaterThanOrEqual",
             ext_call("decimal", value("1.0")),
             ext_call("decimal", value("1.0")))
)]), "conformant")

# datetime methods
probe("A-048-toDate", base_policy("permit", conditions=[condition_when(
    ext_call("toDate", ext_call("datetime", value("2024-01-15T12:00:00Z")))
)]), "conformant")

probe("A-049-toTime", base_policy("permit", conditions=[condition_when(
    ext_call("toTime", ext_call("datetime", value("2024-01-15T12:00:00Z")))
)]), "conformant")

# offset: [receiver_datetime, duration_arg]
probe("A-050-offset", base_policy("permit", conditions=[condition_when(
    ext_call("offset",
             ext_call("datetime", value("2024-01-15T12:00:00Z")),
             ext_call("duration", value("1h")))
)]), "conformant", "offset(datetime, duration) — 2-arg method")

probe("A-051-durationSince", base_policy("permit", conditions=[condition_when(
    ext_call("durationSince",
             ext_call("datetime", value("2024-01-15T12:00:00Z")),
             ext_call("datetime", value("2024-01-01T00:00:00Z")))
)]), "conformant")

# duration query methods
probe("A-052-toDays", base_policy("permit", conditions=[condition_when(
    ext_call("toDays", ext_call("duration", value("48h")))
)]), "conformant")

probe("A-053-toHours", base_policy("permit", conditions=[condition_when(
    ext_call("toHours", ext_call("duration", value("2h30m")))
)]), "conformant")

probe("A-054-toMinutes", base_policy("permit", conditions=[condition_when(
    ext_call("toMinutes", ext_call("duration", value("90m")))
)]), "conformant")

probe("A-055-toSeconds", base_policy("permit", conditions=[condition_when(
    ext_call("toSeconds", ext_call("duration", value("90s")))
)]), "conformant")

probe("A-056-toMilliseconds", base_policy("permit", conditions=[condition_when(
    ext_call("toMilliseconds", ext_call("duration", value("1000ms")))
)]), "conformant")

# Complex nesting
probe("A-057-nested-ite", base_policy("permit", conditions=[condition_when(
    if_then_else(
        binary("==", value(1), value(1)),
        if_then_else(value(True), value(10), value(20)),
        value(0)
    )
)]), "conformant")

probe("A-058-nested-logic", base_policy("permit", conditions=[condition_when(
    binary("&&",
        binary("||", value(True), value(False)),
        unary("!", value(False))
    )
)]), "conformant")

probe("A-059-action-in-set", {
    "effect": "permit",
    "principal": scope_all(),
    "action": {"op": "in", "entities": [
        {"type": "Action", "id": "read"},
        {"type": "Action", "id": "write"},
    ]},
    "resource": scope_all(),
}, "conformant", "action in set scope")


# ── B: EDGE_ZERO — empty args arrays (the NEW-2 class) ───────────────────────
# These are NOT conformant — the extension call has wrong arity.
# Expected behavior: parse_fail at json_unmarshal OR panic at marshal_cedar.
# Panics are findings; parse_fails here are "expected" per honest-reporting rule
# UNLESS cedar-go accepts them (UnmarshalJSON succeeds) and then panics.

METHOD_EXTS = [
    ("lessThan", 2),
    ("lessThanOrEqual", 2),
    ("greaterThan", 2),
    ("greaterThanOrEqual", 2),
    ("isIpv4", 1),
    ("isIpv6", 1),
    ("isLoopback", 1),
    ("isMulticast", 1),
    ("isInRange", 2),
    ("toDate", 1),
    ("toTime", 1),
    ("offset", 2),
    ("durationSince", 2),
    ("toDays", 1),
    ("toHours", 1),
    ("toMinutes", 1),
    ("toSeconds", 1),
    ("toMilliseconds", 1),
]

FUNC_EXTS = [
    ("ip", 1),
    ("decimal", 1),
    ("datetime", 1),
    ("duration", 1),
]

for name, expected_arity in METHOD_EXTS:
    # B-zero: empty args array [] — this is the NEW-2 pattern
    probe(
        f"B-zero-{name}",
        base_policy("permit", conditions=[condition_when({name: []})]),
        "edge_zero",
        f"method {name} with 0 args (expected {expected_arity})"
    )

for name, expected_arity in FUNC_EXTS:
    # B-zero: empty args for constructor functions
    probe(
        f"B-zero-{name}",
        base_policy("permit", conditions=[condition_when({name: []})]),
        "edge_zero",
        f"function {name} with 0 args (expected {expected_arity})"
    )

# B: one arg for 2-arg methods
for name, expected_arity in METHOD_EXTS:
    if expected_arity == 2:
        probe(
            f"B-onearg-{name}",
            base_policy("permit", conditions=[condition_when(
                {name: [value(True)]}  # one arg, needs 2 (receiver + param)
            )]),
            "edge_zero",
            f"method {name} with 1 arg (expected {expected_arity})"
        )

# B: too many args for 1-arg methods
for name, expected_arity in METHOD_EXTS:
    if expected_arity == 1:
        probe(
            f"B-extraarg-{name}",
            base_policy("permit", conditions=[condition_when(
                {name: [value(True), value(True)]}  # 2 args, needs 1
            )]),
            "edge_zero",
            f"method {name} with 2 args (expected {expected_arity})"
        )

# B: correct receiver count but wrong receiver type (still valid JSON)
for name, expected_arity in [("isIpv4", 1), ("isIpv6", 1), ("isLoopback", 1), ("isMulticast", 1)]:
    probe(
        f"B-wrongtype-{name}",
        base_policy("permit", conditions=[condition_when(
            {name: [value("not-an-ip")]}  # correct arity, wrong type
        )]),
        "edge_zero",
        f"method {name} with wrong-type receiver"
    )


# ── C: MALFORMED — malformed JSON structure (parse_fail expected) ─────────────

# C-001: missing effect
probe("C-001-missing-effect", {
    "principal": scope_all(),
    "action": scope_all(),
    "resource": scope_all(),
}, "malformed", "missing effect field")

# C-002: invalid effect
probe("C-002-bad-effect", {
    "effect": "allow",  # must be "permit" or "forbid"
    "principal": scope_all(),
    "action": scope_all(),
    "resource": scope_all(),
}, "malformed")

# C-003: missing scope fields
probe("C-003-missing-principal", {
    "effect": "permit",
    "action": scope_all(),
    "resource": scope_all(),
}, "malformed")

# C-004: bad scope op
probe("C-004-bad-scope-op", {
    "effect": "permit",
    "principal": {"op": "INVALID"},
    "action": scope_all(),
    "resource": scope_all(),
}, "malformed")

# C-005: missing entity in == scope
probe("C-005-scope-eq-no-entity", {
    "effect": "permit",
    "principal": {"op": "=="},
    "action": scope_all(),
    "resource": scope_all(),
}, "malformed")

# C-006: wrong type for entity_type in is scope
probe("C-006-scope-is-num", {
    "effect": "permit",
    "principal": {"op": "is", "entity_type": 42},
    "action": scope_all(),
    "resource": scope_all(),
}, "malformed")

# C-007: condition body is missing
probe("C-007-empty-condition-body", base_policy("permit", conditions=[
    {"kind": "when", "body": {}}
]), "malformed", "empty body in condition")

# C-008: bad condition kind
probe("C-008-bad-condition-kind", base_policy("permit", conditions=[
    {"kind": "INVALID", "body": value(True)}
]), "malformed")

# C-009: unknown extension function
probe("C-009-unknown-ext", base_policy("permit", conditions=[condition_when(
    {"unknownFunction123": [value(1)]}
)]), "malformed", "unknown extension function name")

# C-010: unknown Var
probe("C-010-bad-var", base_policy("permit", conditions=[condition_when(
    {"Var": "notavar"}
)]), "malformed")

# C-011: binaryJSON with missing left
probe("C-011-eq-no-left", base_policy("permit", conditions=[condition_when(
    {"==": {"right": value(1)}}
)]), "malformed")

# C-012: binaryJSON with missing right
probe("C-012-eq-no-right", base_policy("permit", conditions=[condition_when(
    {"==": {"left": value(1)}}
)]), "malformed")

# C-013: unaryJSON with missing arg
probe("C-013-not-no-arg", base_policy("permit", conditions=[condition_when(
    {"!": {}}
)]), "malformed")

# C-014: like with non-string pattern
probe("C-014-like-bad-pattern", base_policy("permit", conditions=[condition_when(
    {"like": {"left": value("hello"), "pattern": 42}}
)]), "malformed")

# C-015: is with missing entity_type
probe("C-015-is-no-entity-type", base_policy("permit", conditions=[condition_when(
    {"is": {"left": principal()}}
)]), "malformed")


# ── D: EXTRAS — extra/unknown fields (testing graceful handling) ──────────────

# D-001: extra field in policy object
probe("D-001-extra-policy-field", {
    "effect": "permit",
    "principal": scope_all(),
    "action": scope_all(),
    "resource": scope_all(),
    "UNKNOWN_FIELD": "should be ignored or fail gracefully",
}, "extras")

# D-002: extra field in scope
probe("D-002-extra-scope-field", {
    "effect": "permit",
    "principal": {"op": "All", "extra": "ignored?"},
    "action": scope_all(),
    "resource": scope_all(),
}, "extras")

# D-003: extra field in condition
probe("D-003-extra-condition-field", base_policy("permit", conditions=[
    {"kind": "when", "body": value(True), "extra": "ignored?"}
]), "extras")

# D-004: extra field in binary node  — nodeJSON uses DisallowUnknownFields
# for known ops, but falls back to extensionJSON for unknown fields
probe("D-004-extra-in-eq-node", base_policy("permit", conditions=[condition_when(
    {"==": {"left": value(1), "right": value(1)}, "extra_field": "should fail or ignored"}
)]), "extras")

# D-005: multiple known ops in one nodeJSON (ambiguous — which one wins?)
probe("D-005-two-ops-in-node", base_policy("permit", conditions=[condition_when(
    {"==": {"left": value(1), "right": value(1)},
     "!=": {"left": value(1), "right": value(2)}}
)]), "extras", "two ops in one node JSON object")

# D-006: deeply nested valid structure
probe("D-006-deep-nest", base_policy("permit", conditions=[condition_when(
    binary("&&",
        binary("&&",
            binary("&&",
                binary("==", value(1), value(1)),
                binary("==", value(2), value(2)),
            ),
            binary("==", value(3), value(3)),
        ),
        binary("==", value(4), value(4)),
    )
)]), "extras", "deeply nested but valid")


# ── E: SCOPE EDGE CASES ───────────────────────────────────────────────────────

# Action in-set with empty entities list
probe("E-001-action-in-empty-set", {
    "effect": "permit",
    "principal": scope_all(),
    "action": {"op": "in", "entities": []},
    "resource": scope_all(),
}, "conformant", "action in empty entity set")

# Action in with both entity and entities (ambiguous)
probe("E-002-action-in-both", {
    "effect": "permit",
    "principal": scope_all(),
    "action": {"op": "in",
               "entity": {"type": "Action", "id": "read"},
               "entities": [{"type": "Action", "id": "write"}]},
    "resource": scope_all(),
}, "extras", "action in with both entity and entities")

# is-in scope (principal)
probe("E-003-principal-is-in", {
    "effect": "permit",
    "principal": {
        "op": "is",
        "entity_type": "Employee",
        "in": {"entity": {"type": "Org", "id": "acme"}}
    },
    "action": scope_all(),
    "resource": scope_all(),
}, "conformant")

# ── F: VALUE edge cases ───────────────────────────────────────────────────────

# Boolean values
probe("F-001-bool-true", base_policy("permit", conditions=[condition_when(value(True))]), "conformant")
probe("F-002-bool-false", base_policy("permit", conditions=[condition_when(value(False))]), "conformant")

# Integer boundary values
probe("F-003-int-max", base_policy("permit", conditions=[condition_when(
    binary("==", value(9223372036854775807), value(9223372036854775807))
)]), "conformant", "i64 max")

probe("F-004-int-min", base_policy("permit", conditions=[condition_when(
    binary("==", value(-9223372036854775808), value(-9223372036854775808))
)]), "conformant", "i64 min")

probe("F-005-int-zero", base_policy("permit", conditions=[condition_when(
    binary("==", value(0), value(0))
)]), "conformant")

# String values
probe("F-006-string-empty", base_policy("permit", conditions=[condition_when(
    binary("==", value(""), value(""))
)]), "conformant")

probe("F-007-string-unicode", base_policy("permit", conditions=[condition_when(
    binary("==", value("café résumé naïve"), value("café résumé naïve"))
)]), "conformant")

probe("F-008-string-escapes", base_policy("permit", conditions=[condition_when(
    binary("==", value("line1\nline2\ttab"), value("line1\nline2\ttab"))
)]), "conformant")

# Entity UID as value
probe("F-009-entity-uid-value", base_policy("permit", conditions=[condition_when(
    binary("==", value({"type": "User", "id": "alice"}), value({"type": "User", "id": "alice"}))
)]), "conformant")

# IP value (extension type as JSON value)
probe("F-010-ip-value", base_policy("permit", conditions=[condition_when(
    binary("==",
        value({"__extn": {"fn": "ip", "arg": "192.168.1.1"}}),
        value({"__extn": {"fn": "ip", "arg": "192.168.1.1"}}))
)]), "conformant", "IP extension value form")

# ── Output ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--list-ids":
        for p in PROBES:
            print(p["id"], p["category"])
    else:
        # NDJSON for the Go harness — just id + policy_json
        for p in PROBES:
            line = {"id": p["id"], "policy_json": p["policy_json"]}
            print(json.dumps(line))
