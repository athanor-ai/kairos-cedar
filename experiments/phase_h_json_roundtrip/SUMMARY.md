# Phase H: JSON-Cedar Policy Round-Trip Widening

Branch: platform/json-roundtrip-widening
Date: 2026-04-25
Cedar: cedar-policy 4.10.0 (Rust), cedar-go v1.6.0 (commit a9a4b1b)

## Aggregate counts (143 probes)

### cedar-go

| Category   |  n | panic | silent_diff | clean | parse_fail |
|------------|-----|-------|-------------|-------|------------|
| conformant |  77 |     0 |           6 |    70 |          1 |
| edge_zero  |  44 |    18 |           0 |    26 |          0 |
| malformed  |  15 |     0 |           0 |     0 |         15 |
| extras     |   7 |     0 |           5 |     1 |          1 |
| TOTAL      | 143 |    18 |          11 |    97 |         17 |

### cedar-policy (Rust CLI)

| Category   |  n | parse_fail | clean | silent_diff |
|------------|-----|------------|-------|-------------|
| conformant |  77 |         10 |    55 |          12 |
| edge_zero  |  44 |         18 |    26 |           0 |
| malformed  |  15 |         15 |     0 |           0 |
| extras     |   7 |          6 |     1 |           0 |
| TOTAL      | 143 |         49 |    82 |          12 |

## Findings

### NEW-3 [CRITICAL PANIC]: All 18 method-style extension calls with zero args

File: disagreements/NEW-3_panic_all_method_extensions_zero_args.md

All IsMethod: true operators in ExtMap panic when given []:
  lessThan, lessThanOrEqual, greaterThan, greaterThanOrEqual,
  isIpv4, isIpv6, isLoopback, isMulticast, isInRange,
  toDate, toTime, offset, durationSince,
  toDays, toHours, toMinutes, toSeconds, toMilliseconds

Root: cedar_marshal.go:199 n.Args[0] without bounds check. No arity validation in UnmarshalJSON.
Rust: accepts {"method": []} -> method_name() (no crash). Neither validates arity.
Class-level bug: IsMethod branch in marshalCedar missing len(Args) >= 1 guard.

| Operator class  | Operators                                | Result |
|-----------------|------------------------------------------|--------|
| Decimal compare | lessThan, lessThanOrEqual, greaterThan, greaterThanOrEqual | PANIC |
| IP predicates   | isIpv4, isIpv6, isLoopback, isMulticast | PANIC |
| IP range        | isInRange                               | PANIC |
| DateTime conv   | toDate, toTime                          | PANIC |
| DateTime arith  | offset, durationSince                   | PANIC |
| Duration query  | toDays, toHours, toMinutes, toSeconds, toMilliseconds | PANIC |
| Constructors    | ip, decimal, datetime, duration         | clean (IsMethod=false) |

### NEW-4 [SILENT DIFF]: Entity-UID short-form changes to Record on round-trip

File: disagreements/NEW-4_silent_diff_entity_uid_as_value.md

Input:  {"Value": {"type": "Group", "id": "admins"}}
Output: {"Record": {"id": {"Value": "admins"}, "type": {"Value": "Group"}}}

AST type changes Value(EntityUID) -> Record. Cedar text ambiguity loses type info.
Rust rejects short-form entity UID (requires __entity envelope). Cross-impl acceptance divergence.
Affected: A-032-in-expr, F-009-entity-uid-value, A-025b-is-in-expr

### NEW-5 [SILENT DIFF]: neg(Value(n)) folds to Value(-n) on round-trip

File: disagreements/NEW-5_silent_diff_neg_fold.md

Input {"neg": {"arg": {"Value": 5}}} -> Output {"Value": -5}
Cedar text normalizes -(5) to integer literal -5. Semantically equivalent.
Rust preserves neg form. Representation-only difference.

### NEW-6 [SILENT DIFF]: Extension value form {__extn} -> call form {fn: [arg]}

File: disagreements/NEW-6_silent_diff_extension_value_form.md

Input {"Value": {"__extn": {"fn": "ip", "arg": "192.168.1.1"}}}
Output {"ip": [{"Value": "192.168.1.1"}]}
Inherent: Cedar text conflates value construction and function call for extension types.

### NEW-7 [SILENT DIFF]: action entities:[] dropped on round-trip

File: disagreements/NEW-7_silent_diff_action_in_empty_entities.md

Input {"action": {"op": "in", "entities": []}} -> Output {"action": {"op": "in"}}
Empty entities array lost; re-parsing output would fail.

### OBS-1 [INFORMATIONAL]: Extra fields silently dropped; two-op node picks one

File: disagreements/OBS-1_silent_diff_extra_fields_silently_dropped.md

Unknown JSON fields dropped at policy/scope/condition level.
Two-op body node (== and !=) silently keeps one, drops other.

## Predicted vs Found

Predicted: panics on more than one operator class.
Found: ALL 18 method-style operators panic. Class-level missing bounds check.
Constructor functions (IsMethod=false) unaffected by different code path.

Predicted: silent information drops.
Found: 4 classes confirmed (NEW-4 through NEW-7).

Predicted: cross-impl divergence on malformed input acceptance.
Found: Rust accepts zero-arg method calls; cedar-go panics. Rust rejects short-form
entity UIDs; cedar-go accepts with silent type change.

## Honest reporting

Genuine bugs: 18 panics on edge_zero inputs. {"method": []} is valid JSON with a
recognized key; UnmarshalJSON accepts it, MarshalCedar crashes. Attacker-triggerable.

Expected behaviors not counted as bugs:
  - Rust parse_fail on probes missing conditions field (probe omits optional field Rust requires)
  - like pattern format difference (cedar-go string form vs Rust array form)
  - All 15 malformed probe parse_fails are expected

Borderline: NEW-4 entity UID short form accepted by cedar-go as a spec extension;
silent type change is unintended consequence, not an independent defect.
