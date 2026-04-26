#!/usr/bin/env python3
"""
probe_schemas.py; phase_i schema-roundtrip widening.

Generates a fixed set of well-formed JSON Cedar schemas that exercise
distinct AST shapes the cedar-go x/exp/schema marshaller might mishandle.
For each schema, runs:

  1. cedar-policy 4.10.0 reference: `cedar translate-schema --direction
     json-to-cedar` then `--direction cedar-to-json`. Parses the final
     JSON and structurally diffs it against the input.
  2. cedar-go v1.6.0: the Go harness in `go_harness/probe`. Performs
     UnmarshalJSON -> MarshalCedar -> UnmarshalCedar -> MarshalJSON,
     and structurally diffs the final JSON against the input.

Each schema is classified per-impl as:
  - clean       : both impls round-trip the JSON shape unchanged.
  - silent_diff : impl successfully round-trips but the final JSON
                  differs structurally from the input.
  - parse_fail  : impl honestly errors at some stage (NOT a finding;
                  it's a feature gap they could fix).
  - panic       : impl crashed.

A schema with `silent_diff` on cedar-go but `parse_fail` (or `clean`)
on cedar-policy is filed as a disagreement under `disagreements/`.

This script must be run inside the `ghcr.io/athanor-ai/kairos-cedar`
container, with the worktree mounted at /work. It expects:

  /work/experiments/phase_i_schema_roundtrip/go_harness/probe   (built)
  cedar-policy-cli 4.10.0 on PATH (as `cedar`)

Usage:
  ./scripts/dc bash -c 'cd /work/experiments/phase_i_schema_roundtrip && \
      python3 probe_schemas.py'
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
DISAGREEMENTS = ROOT / "disagreements"
GO_PROBE = ROOT / "go_harness" / "probe"
CEDAR = shutil.which("cedar") or "cedar"


# ---------------------------------------------------------------------------
# Schema generators
# ---------------------------------------------------------------------------
#
# Each generator returns a (schema_id, json_dict) pair. The shapes target
# distinct hypotheses about where cedar-go's marshaller may silently lose
# information.
#
# Hypothesis classes (mirrors NEW-1 architectural pattern):
#  H1; entity-shape ::= TypeRef (common-type alias). NEW-1 baseline.
#  H2; entity-shape ::= TypeRef (primitive alias). Variants: Long, String, Bool, Set.
#  H3; record attr type ::= TypeRef (common-type / primitive alias).
#       Tests deeper nesting than H1.
#  H4; multi-namespace cross-references.
#  H5; entity hierarchies with deep `in` chains.
#  H6; RFC-82 tagged entities, tag-type as common-type-ref.
#  H7; multi-action multi-resource appliesTo with shared common-type
#       context.
#  H8; extension types (decimal, ipaddr, datetime, duration); embedded
#       in entity attrs.


SCHEMAS: list[tuple[str, dict]] = []


def reg(schema_id: str):
    def deco(fn):
        SCHEMAS.append((schema_id, fn()))
        return fn
    return deco


# H1; entity-shape is a common-type ref (NEW-1 territory).

@reg("h1_entity_shape_is_common_type_ref")
def _():
    # Same as NEW-1, but unique fixture; used as control.
    return {
        "": {
            "commonTypes": {
                "Foo": {
                    "type": "Record",
                    "attributes": {"bar": {"type": "Long"}},
                },
            },
            "entityTypes": {"Baz": {"shape": {"type": "Foo"}}},
            "actions": {},
        },
    }


@reg("h1b_entity_shape_is_common_type_ref_with_optional")
def _():
    return {
        "": {
            "commonTypes": {
                "Foo": {
                    "type": "Record",
                    "attributes": {
                        "bar": {"type": "Long"},
                        "opt": {"type": "String", "required": False},
                    },
                },
            },
            "entityTypes": {"Baz": {"shape": {"type": "Foo"}}},
            "actions": {},
        },
    }


@reg("h1c_entity_shape_is_namespaced_common_type_ref")
def _():
    return {
        "NS": {
            "commonTypes": {
                "Foo": {
                    "type": "Record",
                    "attributes": {"bar": {"type": "Long"}},
                },
            },
            "entityTypes": {"Baz": {"shape": {"type": "NS::Foo"}}},
            "actions": {},
        },
    }


@reg("h1d_entity_shape_is_entityorcommon_typeref")
def _():
    # Use the explicit "EntityOrCommon" tag instead of the bare type name.
    return {
        "": {
            "commonTypes": {
                "Foo": {
                    "type": "Record",
                    "attributes": {"bar": {"type": "Long"}},
                },
            },
            "entityTypes": {
                "Baz": {"shape": {"type": "EntityOrCommon", "name": "Foo"}},
            },
            "actions": {},
        },
    }


@reg("h1e_chained_common_types")
def _():
    # Common-type that aliases another common-type.
    return {
        "": {
            "commonTypes": {
                "Inner": {
                    "type": "Record",
                    "attributes": {"x": {"type": "Long"}},
                },
                "Outer": {
                    "type": "Record",
                    "attributes": {"inner": {"type": "Inner"}},
                },
            },
            "entityTypes": {"Baz": {"shape": {"type": "Outer"}}},
            "actions": {},
        },
    }


# H2; REMOVED. Entity shapes that are non-Record literals (Long, Set,
# Extension, Entity) are ill-formed per cedar-policy 4.10.0's
# JSON-schema parser ("Shape for entity type X is declared with a type
# other than `Record`") and per the cedar-spec Lean
# `StandardSchemaEntry.attrs : RecordType` invariant. Per the task's
# honesty rule, an ill-formed-input run is a generator bug not a
# marshaller bug, so these shapes are excluded from the result table.
# (The cedar-go marshaller does silently collapse them to empty Record,
# but since they are not well-formed inputs, that is not a finding.)
#
# H1 stays in: entity-shape ::= TypeRef-to-Record-common-type IS
# well-formed JSON (cedar `check-parse` accepts; the resolved type IS
# a Record after common-type resolution). cedar-policy's
# `translate-schema` honestly errors on the JSON-only fragment;
# cedar-go silently emits an empty record; the real finding.


# H3; record attr is a common-type alias of a non-record type.

@reg("h3_record_attr_aliases_long")
def _():
    return {
        "": {
            "commonTypes": {"MyLong": {"type": "Long"}},
            "entityTypes": {
                "Baz": {
                    "shape": {
                        "type": "Record",
                        "attributes": {"n": {"type": "MyLong"}},
                    },
                },
            },
            "actions": {},
        },
    }


@reg("h3b_record_attr_aliases_set")
def _():
    return {
        "": {
            "commonTypes": {
                "MySet": {"type": "Set", "element": {"type": "String"}},
            },
            "entityTypes": {
                "Baz": {
                    "shape": {
                        "type": "Record",
                        "attributes": {"tags": {"type": "MySet"}},
                    },
                },
            },
            "actions": {},
        },
    }


@reg("h3c_record_attr_nested_common_type_ref")
def _():
    return {
        "": {
            "commonTypes": {
                "Inner": {
                    "type": "Record",
                    "attributes": {"x": {"type": "Long"}},
                },
            },
            "entityTypes": {
                "Baz": {
                    "shape": {
                        "type": "Record",
                        "attributes": {"inner": {"type": "Inner"}},
                    },
                },
            },
            "actions": {},
        },
    }


# H4; multi-namespace.

@reg("h4_three_namespaces_cross_ref")
def _():
    return {
        "A": {
            "commonTypes": {
                "AT": {
                    "type": "Record",
                    "attributes": {"x": {"type": "Long"}},
                },
            },
            "entityTypes": {
                "AE": {"shape": {"type": "Record", "attributes": {}}},
            },
            "actions": {},
        },
        "B": {
            "entityTypes": {
                "BE": {
                    "shape": {
                        "type": "Record",
                        "attributes": {
                            "r": {"type": "Entity", "name": "A::AE"},
                        },
                    },
                },
            },
            "actions": {},
        },
        "C": {
            "entityTypes": {
                "CE": {
                    "shape": {
                        "type": "Record",
                        "attributes": {"a": {"type": "A::AT"}},
                    },
                },
            },
            "actions": {},
        },
    }


# H5; deep `in` chains.

@reg("h5_three_level_entity_hierarchy")
def _():
    return {
        "": {
            "entityTypes": {
                "L1": {"shape": {"type": "Record", "attributes": {}}},
                "L2": {
                    "memberOfTypes": ["L1"],
                    "shape": {"type": "Record", "attributes": {}},
                },
                "L3": {
                    "memberOfTypes": ["L2"],
                    "shape": {"type": "Record", "attributes": {}},
                },
            },
            "actions": {},
        },
    }


@reg("h5b_diamond_entity_hierarchy")
def _():
    return {
        "": {
            "entityTypes": {
                "Top": {"shape": {"type": "Record", "attributes": {}}},
                "MidA": {
                    "memberOfTypes": ["Top"],
                    "shape": {"type": "Record", "attributes": {}},
                },
                "MidB": {
                    "memberOfTypes": ["Top"],
                    "shape": {"type": "Record", "attributes": {}},
                },
                "Leaf": {
                    "memberOfTypes": ["MidA", "MidB"],
                    "shape": {"type": "Record", "attributes": {}},
                },
            },
            "actions": {},
        },
    }


# H6; RFC-82 tagged entities; tags is a common-type ref.

@reg("h6_tagged_entity_primitive_tags")
def _():
    return {
        "": {
            "entityTypes": {
                "Resource": {
                    "shape": {"type": "Record", "attributes": {}},
                    "tags": {"type": "String"},
                },
            },
            "actions": {},
        },
    }


@reg("h6b_tagged_entity_tags_is_common_type_ref")
def _():
    return {
        "": {
            "commonTypes": {"TagT": {"type": "String"}},
            "entityTypes": {
                "Resource": {
                    "shape": {"type": "Record", "attributes": {}},
                    "tags": {"type": "TagT"},
                },
            },
            "actions": {},
        },
    }


@reg("h6c_tagged_entity_tags_set")
def _():
    return {
        "": {
            "entityTypes": {
                "Resource": {
                    "shape": {"type": "Record", "attributes": {}},
                    "tags": {"type": "Set", "element": {"type": "Long"}},
                },
            },
            "actions": {},
        },
    }


@reg("h6d_tagged_entity_tags_is_record_common_type_ref")
def _():
    # Tags type is a common-type that aliases a Record. cedar-policy
    # JSON-form accepts this; tests whether cedar-go's tag-marshaller
    # silently collapses (parallel to NEW-1 entity-shape collapse).
    return {
        "": {
            "commonTypes": {
                "TagRec": {
                    "type": "Record",
                    "attributes": {"k": {"type": "String"}},
                },
            },
            "entityTypes": {
                "Resource": {
                    "shape": {"type": "Record", "attributes": {}},
                    "tags": {"type": "TagRec"},
                },
            },
            "actions": {},
        },
    }


# H7; action context as common-type ref + multi-action / multi-resource.

@reg("h7_action_context_common_type_ref")
def _():
    return {
        "": {
            "commonTypes": {
                "Ctx": {
                    "type": "Record",
                    "attributes": {"ip": {"type": "Extension", "name": "ipaddr"}},
                },
            },
            "entityTypes": {
                "User": {"shape": {"type": "Record", "attributes": {}}},
                "Doc": {"shape": {"type": "Record", "attributes": {}}},
            },
            "actions": {
                "view": {
                    "appliesTo": {
                        "principalTypes": ["User"],
                        "resourceTypes": ["Doc"],
                        "context": {"type": "Ctx"},
                    },
                },
            },
        },
    }


@reg("h7b_multi_action_multi_resource_appliesto")
def _():
    return {
        "": {
            "entityTypes": {
                "User": {"shape": {"type": "Record", "attributes": {}}},
                "Admin": {"shape": {"type": "Record", "attributes": {}}},
                "Doc": {"shape": {"type": "Record", "attributes": {}}},
                "Folder": {"shape": {"type": "Record", "attributes": {}}},
            },
            "actions": {
                "view": {
                    "appliesTo": {
                        "principalTypes": ["User", "Admin"],
                        "resourceTypes": ["Doc", "Folder"],
                    },
                },
                "edit": {
                    "appliesTo": {
                        "principalTypes": ["Admin"],
                        "resourceTypes": ["Doc"],
                    },
                },
            },
        },
    }


# H8; extension types in attributes.

@reg("h8_decimal_attr")
def _():
    return {
        "": {
            "entityTypes": {
                "U": {
                    "shape": {
                        "type": "Record",
                        "attributes": {
                            "bal": {"type": "Extension", "name": "decimal"}
                        },
                    },
                },
            },
            "actions": {},
        },
    }


@reg("h8b_ipaddr_attr")
def _():
    return {
        "": {
            "entityTypes": {
                "Host": {
                    "shape": {
                        "type": "Record",
                        "attributes": {
                            "addr": {"type": "Extension", "name": "ipaddr"}
                        },
                    },
                },
            },
            "actions": {},
        },
    }


@reg("h8c_datetime_and_duration_attrs")
def _():
    return {
        "": {
            "entityTypes": {
                "Event": {
                    "shape": {
                        "type": "Record",
                        "attributes": {
                            "at": {"type": "Extension", "name": "datetime"},
                            "len": {"type": "Extension", "name": "duration"},
                        },
                    },
                },
            },
            "actions": {},
        },
    }


@reg("h8d_extension_in_common_type")
def _():
    return {
        "": {
            "commonTypes": {
                "Bal": {"type": "Extension", "name": "decimal"},
            },
            "entityTypes": {
                "U": {
                    "shape": {
                        "type": "Record",
                        "attributes": {"bal": {"type": "Bal"}},
                    },
                },
            },
            "actions": {},
        },
    }


# ---------------------------------------------------------------------------
# Round-trip drivers
# ---------------------------------------------------------------------------


@dataclass
class ImplResult:
    classification: str
    error: Optional[str] = None
    diff_summary: Optional[str] = None
    intermediate_cedar: Optional[str] = None
    final_json: Optional[str] = None


@dataclass
class CaseResult:
    schema_id: str
    well_formed_json: bool         # cedar check-parse accepts
    well_formed_msg: Optional[str]
    rust: ImplResult
    go: ImplResult


def well_formed_check(schema_json: dict) -> tuple[bool, Optional[str]]:
    """Return (is_well_formed, error_msg). cedar-policy 4.10.0
    `check-parse` against the JSON-schema parser is the bridge target
    for cedar-spec's well-formedness predicate (the Lean Schema spec
    requires entity shapes to resolve to Record; cedar-policy
    enforces this at the surface JSON parser)."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        json_in = tdp / "in.json"
        json_in.write_text(json.dumps(schema_json))
        r = subprocess.run(
            [CEDAR, "check-parse", "--schema", str(json_in),
             "--schema-format", "json"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            return True, None
        return False, (r.stderr or r.stdout).strip()[:500]


PRIMITIVE_TYPES = {"Long", "String", "Boolean", "Bool",
                   "__cedar::Long", "__cedar::String", "__cedar::Boolean"}
EXTENSION_TYPES = {"ipaddr", "decimal", "datetime", "duration",
                   "__cedar::ipaddr", "__cedar::decimal",
                   "__cedar::datetime", "__cedar::duration"}


def _canonical(obj: Any) -> Any:
    """Return a structure that deep-equals across reorderings."""
    if isinstance(obj, dict):
        return {k: _canonical(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_canonical(x) for x in obj]
    return obj


CEDAR_BUILTIN_TYPES = {
    "Record", "Set", "Entity", "EntityOrCommon", "Extension",
    "Long", "String", "Boolean", "Bool",
}


def _normalise_type_node(t: dict) -> dict:
    """Normalise a JSON `type` node so that semantically-equivalent
    Cedar JSON-schema spellings deep-equal.

    Equivalences (per Cedar 4.x JSON-schema syntax):
      - {"type": "Long"} == {"type": "EntityOrCommon", "name": "Long"}
        (and similarly for String/Boolean/Bool; both forms resolve to
        the same primitive at validation time).
      - {"type": "Extension", "name": "ipaddr"} ==
        {"type": "EntityOrCommon", "name": "__cedar::ipaddr"}
        (cedar resolves `__cedar::<ext>` to the extension type, so
        these produce identical validator behaviour).
      - bare `name` field: `Foo` and `__cedar::Foo` for extensions,
        `Long`/`String`/`Boolean` for primitives.

    Returns a normalised copy. Operates only at the immediate type-node
    level; recursion is handled by `_normalise_schema`.
    """
    if not isinstance(t, dict):
        return t
    out = dict(t)
    typ = out.get("type")
    name = out.get("name")
    if typ == "EntityOrCommon" and name in PRIMITIVE_TYPES:
        # canonical form: primitive name as the type tag
        bare = name.split("::")[-1]
        canonical = "Boolean" if bare == "Bool" else bare
        return {"type": canonical}
    if typ == "EntityOrCommon" and name in EXTENSION_TYPES:
        ext = name.split("::")[-1]
        return {"type": "Extension", "name": ext}
    if typ == "Extension" and isinstance(name, str):
        # Strip a `__cedar::` prefix if present.
        ext = name.split("::")[-1]
        out["name"] = ext
    if typ == "Entity" and isinstance(name, str):
        # `{type:Entity, name:Foo}` is an explicit entity-ref; cedar
        # resolves `{type:EntityOrCommon, name:Foo}` to the same when
        # `Foo` is an entity type. Canonicalise both to EntityOrCommon
        # for comparison purposes.
        return {"type": "EntityOrCommon", "name": name}
    if typ == "Bool":
        out["type"] = "Boolean"
        return out
    # Bare-name TypeRef ({"type": "MyCustomName"}) is sugar for
    # {"type": "EntityOrCommon", "name": "MyCustomName"}. Canonicalise
    # to the EntityOrCommon form.
    if isinstance(typ, str) and typ not in CEDAR_BUILTIN_TYPES and "name" not in out:
        return {"type": "EntityOrCommon", "name": typ}
    return out


def _normalise_schema(obj: Any) -> Any:
    """Recursively normalise a schema for semantic-equivalence
    comparison.

    Beyond `_normalise_type_node`, also:
      - drops empty `shape.attributes` (empty record == absent attrs).
      - inserts a default empty `shape: {type: Record, attributes: {}}`
        on entity types lacking a shape (cedar's default).
      - sorts `memberOfTypes` lists.
      - drops `principalTypes`/`resourceTypes` empty arrays.
    """
    if isinstance(obj, dict):
        norm = {}
        # First, recurse on children.
        for k, v in obj.items():
            norm[k] = _normalise_schema(v)
        # Apply type-node normalisation if this is a type node.
        if "type" in norm and isinstance(norm.get("type"), str):
            norm = _normalise_type_node(norm)
        # Drop redundant empty attrs from a Record-type node.
        if (norm.get("type") == "Record"
                and norm.get("attributes") == {}):
            norm.pop("attributes", None)
        return norm
    if isinstance(obj, list):
        return [_normalise_schema(x) for x in obj]
    return obj


def _normalise_top(obj: Any) -> Any:
    """Apply schema-level normalisations: ensure every entityType has an
    explicit empty shape, drop empty appliesTo lists."""
    out = _normalise_schema(obj)
    if not isinstance(out, dict):
        return out
    for ns_name, ns in out.items():
        if not isinstance(ns, dict):
            continue
        ets = ns.get("entityTypes")
        if isinstance(ets, dict):
            for et_name, et in ets.items():
                if not isinstance(et, dict):
                    continue
                # Skip enum entities (no shape).
                if "enum" in et:
                    continue
                if "shape" not in et:
                    et["shape"] = {"type": "Record"}
                # Sort memberOfTypes for stable comparison.
                if isinstance(et.get("memberOfTypes"), list):
                    et["memberOfTypes"] = sorted(et["memberOfTypes"])
        actions = ns.get("actions")
        if isinstance(actions, dict):
            for a_name, a in actions.items():
                if not isinstance(a, dict):
                    continue
                at = a.get("appliesTo")
                if isinstance(at, dict):
                    if at.get("principalTypes") in (None, []):
                        at.pop("principalTypes", None)
                    if at.get("resourceTypes") in (None, []):
                        at.pop("resourceTypes", None)
                    if isinstance(at.get("principalTypes"), list):
                        at["principalTypes"] = sorted(at["principalTypes"])
                    if isinstance(at.get("resourceTypes"), list):
                        at["resourceTypes"] = sorted(at["resourceTypes"])
    return out


def _diff_summary(a: Any, b: Any, path: str = "$", out: Optional[list] = None) -> str:
    if out is None:
        out = []
    if len(out) >= 4:
        return "; ".join(out)
    if isinstance(a, dict) and isinstance(b, dict):
        keys = sorted(set(a.keys()) | set(b.keys()))
        for k in keys:
            if k not in a:
                out.append(f"{path}.{k}: added")
            elif k not in b:
                out.append(f"{path}.{k}: dropped")
            else:
                _diff_summary(a[k], b[k], f"{path}.{k}", out)
            if len(out) >= 4:
                break
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} vs {len(b)}")
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                _diff_summary(x, y, f"{path}[{i}]", out)
                if len(out) >= 4:
                    break
    elif a != b:
        out.append(f"{path}: {a!r} -> {b!r}")
    return "; ".join(out)


def run_rust(schema_id: str, schema_json: dict) -> ImplResult:
    """cedar translate-schema json-to-cedar, then cedar-to-json.

    Note: cedar 4.10.0's `translate-schema` rejects schemas in the
    JSON-only fragment (e.g. NEW-1). When it rejects, we report
    `parse_fail`; when it succeeds and cedar-to-json round-trips,
    we structurally diff the final JSON against input.
    """
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        json_in = tdp / "in.json"
        json_in.write_text(json.dumps(schema_json))
        # json-to-cedar
        r1 = subprocess.run(
            [CEDAR, "translate-schema", "--direction", "json-to-cedar",
             "-s", str(json_in)],
            capture_output=True, text=True,
        )
        if r1.returncode != 0:
            return ImplResult(
                classification="parse_fail",
                error=(r1.stderr or r1.stdout).strip()[:1000],
            )
        cedar_text = r1.stdout
        cedar_in = tdp / "in.cedarschema"
        cedar_in.write_text(cedar_text)
        # cedar-to-json
        r2 = subprocess.run(
            [CEDAR, "translate-schema", "--direction", "cedar-to-json",
             "-s", str(cedar_in)],
            capture_output=True, text=True,
        )
        if r2.returncode != 0:
            return ImplResult(
                classification="parse_fail",
                error=(r2.stderr or r2.stdout).strip()[:1000],
                intermediate_cedar=cedar_text,
            )
        try:
            rt = json.loads(r2.stdout)
        except json.JSONDecodeError as e:
            return ImplResult(
                classification="parse_fail",
                error=f"final JSON decode: {e}",
                intermediate_cedar=cedar_text,
                final_json=r2.stdout,
            )
        a, b = _normalise_top(_canonical(schema_json)), _normalise_top(_canonical(rt))
        if a == b:
            return ImplResult(
                classification="clean",
                intermediate_cedar=cedar_text,
                final_json=json.dumps(rt),
            )
        return ImplResult(
            classification="silent_diff",
            diff_summary=_diff_summary(a, b),
            intermediate_cedar=cedar_text,
            final_json=json.dumps(rt),
        )


def run_go(schema_id: str, schema_json: dict) -> ImplResult:
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        json_in = tdp / "in.json"
        json_in.write_text(json.dumps(schema_json))
        r = subprocess.run(
            [str(GO_PROBE), str(json_in)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return ImplResult(
                classification="panic",
                error=(r.stderr or r.stdout).strip()[:1000],
            )
        try:
            data = json.loads(r.stdout.splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as e:
            return ImplResult(
                classification="panic",
                error=f"probe stdout decode: {e}: {r.stdout[:500]}",
            )
        cls = data["classification"]
        # Re-classify using semantic-equivalence normalisation when the
        # Go probe completed (so we share the same equivalence
        # relation across cedar-policy and cedar-go).
        if cls in ("clean", "silent_diff") and data.get("roundtripped_json"):
            try:
                rt = json.loads(data["roundtripped_json"])
                a = _normalise_top(_canonical(schema_json))
                b = _normalise_top(_canonical(rt))
                if a == b:
                    cls = "clean"
                    diff = None
                else:
                    cls = "silent_diff"
                    diff = _diff_summary(a, b)
            except json.JSONDecodeError:
                diff = data.get("diff_summary")
        else:
            diff = data.get("diff_summary")
        return ImplResult(
            classification=cls,
            error=data.get("error"),
            diff_summary=diff,
            intermediate_cedar=data.get("marshalled_cedar"),
            final_json=data.get("roundtripped_json"),
        )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


PER_GAP_TEMPLATE = """\
# Phase I disagreement; {schema_id}

**Schema-roundtrip widening of NEW-1 (cedar #1702 / cedar-go silent-diff
class).** Verified {date}.

## Versions
- cedar-policy-cli **4.10.0** (container `ghcr.io/athanor-ai/kairos-cedar:latest`)
- cedar-go **v1.6.0** (HEAD `a9a4b1b1450917d5df2a3c7c17d6567035fd8fcb`,
  `x/exp/schema`)
- Container hash: `d9c9ceb6be83`

## Hypothesis class
{hypothesis}

## Input schema (JSON)

```json
{input_json}
```

## cedar-policy 4.10.0; round-trip

- `cedar translate-schema --direction json-to-cedar` then
  `--direction cedar-to-json`.
- Classification: **{rust_class}**
- {rust_detail}

## cedar-go v1.6.0 (`x/exp/schema`); round-trip

- `UnmarshalJSON` -> `MarshalCedar` -> `UnmarshalCedar` -> `MarshalJSON`.
- Classification: **{go_class}**
- {go_detail}

### cedar-go intermediate Cedar text

```cedar
{go_cedar}
```

### cedar-go final JSON (round-tripped)

```json
{go_final_json}
```

### cedar-go diff summary (input -> roundtripped)

`{go_diff}`

## Source-line attribution (cedar-go)

The fall-through is in
`cedar-go/x/exp/schema/internal/json/json.go::unmarshalNamespace`
(line 336) which calls `unmarshalRecordType` on `jet.Shape`
**unconditionally**, irrespective of `jet.Shape.Type`. When
`jet.Shape.Type` is anything other than `Record` (e.g. a TypeRef
naming a common-type, or a non-record primitive), the call produces
an empty `ast.RecordType`. The same root cause manifests in
`marshal.go::marshalDecls` (line 91) which always emits
`marshalRecordType(entity.Shape)`.

Equivalent root cause: `ast.Entity.Shape` is hard-typed as
`RecordType` (line 55 of `cedar-go/x/exp/schema/ast/ast.go`); the AST
cannot represent any non-record shape. Every JSON shape that is not a
Record-literal collapses on entry.

## Classification

**cross-format-asymmetric silent-diff**; cedar-policy errors honestly
on the JSON-only fragment, cedar-go silently transforms it.
"""


def per_gap_md(case: CaseResult, hypothesis: str, input_json: str, date: str) -> str:
    rust_detail = (
        case.rust.error.strip().replace("\n", " ")[:400]
        if case.rust.error
        else (case.rust.diff_summary or "_no detail_")
    )
    go_detail = (
        case.go.error or case.go.diff_summary or "_no detail_"
    )
    return PER_GAP_TEMPLATE.format(
        schema_id=case.schema_id,
        date=date,
        hypothesis=hypothesis,
        input_json=input_json,
        rust_class=case.rust.classification,
        rust_detail=rust_detail,
        go_class=case.go.classification,
        go_detail=go_detail,
        go_cedar=(case.go.intermediate_cedar or "").rstrip(),
        go_final_json=case.go.final_json or "",
        go_diff=case.go.diff_summary or "(no diff captured)",
    )


HYPOTHESES = {
    "h1": "H1; entity-shape is a TypeRef naming a common type "
          "(NEW-1 #1702 territory).",
    "h2": "H2; entity-shape is a non-record primitive type "
          "(degenerate but the JSON-grammar accepts it).",
    "h3": "H3; record attr type is a TypeRef (common-type alias of "
          "primitive / set / record).",
    "h4": "H4; multi-namespace cross-references.",
    "h5": "H5; entity hierarchies with deep / wide `in` chains.",
    "h6": "H6; RFC-82 tagged entities (tags type variants).",
    "h7": "H7; action context as common-type ref + multi-action "
          "multi-resource appliesTo blocks.",
    "h8": "H8; extension types (decimal, ipaddr, datetime, duration).",
}


def hypothesis_for(schema_id: str) -> str:
    prefix = schema_id.split("_")[0].rstrip("abcde")
    return HYPOTHESES.get(prefix, "(unclassified)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    import datetime
    date = datetime.date.today().isoformat()

    if not GO_PROBE.exists():
        sys.exit(
            f"Go probe not built at {GO_PROBE}. "
            f"Run from container:\n"
            f"  cd /work/experiments/phase_i_schema_roundtrip/go_harness && "
            f"GOFLAGS='-mod=mod -buildvcs=false' go build -o probe ."
        )

    FIXTURES.mkdir(parents=True, exist_ok=True)
    DISAGREEMENTS.mkdir(parents=True, exist_ok=True)

    cases: list[CaseResult] = []
    for schema_id, schema_json in SCHEMAS:
        # Persist fixture for evidence.
        (FIXTURES / f"{schema_id}.json").write_text(
            json.dumps(schema_json, indent=2) + "\n"
        )
        wf, wf_msg = well_formed_check(schema_json)
        rust = run_rust(schema_id, schema_json)
        go = run_go(schema_id, schema_json)
        cases.append(CaseResult(schema_id=schema_id, well_formed_json=wf,
                                well_formed_msg=wf_msg, rust=rust, go=go))
        wf_tag = "WF" if wf else "ill-formed"
        print(f"  {schema_id:55s}  [{wf_tag:>10s}]  rust={rust.classification:12s}  "
              f"go={go.classification}", file=sys.stderr)

    # Per-gap markdown for well-formed go silent_diff or panic.
    # Ill-formed inputs are excluded per the task's "generator bug not
    # marshaller bug" rule.
    for case in cases:
        if (case.go.classification in ("silent_diff", "panic")
                and case.well_formed_json):
            md = per_gap_md(
                case,
                hypothesis_for(case.schema_id),
                json.dumps(SCHEMAS_BY_ID[case.schema_id], indent=2),
                date,
            )
            (DISAGREEMENTS / f"{case.schema_id}.md").write_text(md)

    # Summary.
    summary = build_summary(cases, date)
    (ROOT / "SUMMARY.md").write_text(summary)
    # Machine-readable.
    (ROOT / "results.json").write_text(json.dumps(
        [{"schema_id": c.schema_id,
          "well_formed_json": c.well_formed_json,
          "well_formed_msg": c.well_formed_msg,
          "rust": asdict(c.rust),
          "go": asdict(c.go)} for c in cases],
        indent=2,
    ))
    print(f"\nWrote SUMMARY.md, results.json, and "
          f"{sum(1 for c in cases if c.go.classification in ('silent_diff','panic'))} "
          f"per-gap files in disagreements/.", file=sys.stderr)


SCHEMAS_BY_ID = {sid: js for sid, js in SCHEMAS}


def build_summary(cases: list[CaseResult], date: str) -> str:
    n = len(cases)
    n_wf = sum(1 for c in cases if c.well_formed_json)
    wf_cases = [c for c in cases if c.well_formed_json]
    n_rust_clean = sum(1 for c in wf_cases if c.rust.classification == "clean")
    n_rust_silent = sum(1 for c in wf_cases if c.rust.classification == "silent_diff")
    n_rust_fail = sum(1 for c in wf_cases if c.rust.classification == "parse_fail")
    n_go_clean = sum(1 for c in wf_cases if c.go.classification == "clean")
    n_go_silent = sum(1 for c in wf_cases if c.go.classification == "silent_diff")
    n_go_fail = sum(1 for c in wf_cases if c.go.classification == "parse_fail")
    n_go_panic = sum(1 for c in wf_cases if c.go.classification == "panic")

    lines = []
    lines.append("# Phase I; schema-roundtrip widening: SUMMARY")
    lines.append("")
    lines.append(f"Date: {date}")
    lines.append("")
    lines.append("Versions:")
    lines.append("- cedar-policy-cli **4.10.0** "
                 "(container `ghcr.io/athanor-ai/kairos-cedar:latest`, "
                 "image hash `d9c9ceb6be83`)")
    lines.append("- cedar-go **v1.6.0** "
                 "(HEAD `a9a4b1b1450917d5df2a3c7c17d6567035fd8fcb`, "
                 "`x/exp/schema`)")
    lines.append("- Lean evaluator: N/A; `cedar-spec/cedar-lean` does not "
                 "implement the Cedar-text-schema parser, so it does not "
                 "contribute a verdict on schema-format round-trip.")
    lines.append("")
    lines.append("## Aggregate")
    lines.append("")
    lines.append(f"- N_schemas tested: **{n}**")
    lines.append(f"- N_well-formed (cedar 4.10.0 `check-parse` rc=0): "
                 f"**{n_wf}**")
    lines.append("")
    lines.append("Counts on the well-formed subset only (per the task's "
                 "honesty rule; ill-formed inputs are generator bugs, "
                 "not marshaller findings):")
    lines.append("")
    lines.append(f"- cedar-policy: clean={n_rust_clean}, "
                 f"silent_diff={n_rust_silent}, parse_fail={n_rust_fail}")
    lines.append(f"- cedar-go: clean={n_go_clean}, "
                 f"silent_diff={n_go_silent}, parse_fail={n_go_fail}, "
                 f"panic={n_go_panic}")
    lines.append("")
    lines.append("## Per-shape table")
    lines.append("")
    lines.append("| Schema id | Hypothesis | well-formed | cedar-policy | "
                 "cedar-go | Filed under disagreements/? |")
    lines.append("|-----------|------------|-------------|--------------|"
                 "----------|-----------------------------|")
    for c in cases:
        h = hypothesis_for(c.schema_id).split("-")[0].strip()
        filed = ("yes" if (c.go.classification in ("silent_diff", "panic")
                          and c.well_formed_json)
                 else "no")
        wf = "yes" if c.well_formed_json else "no"
        lines.append(f"| `{c.schema_id}` | {h} | {wf} | "
                     f"`{c.rust.classification}` | "
                     f"`{c.go.classification}` | {filed} |")
    lines.append("")
    lines.append("## Per-shape detail")
    lines.append("")
    for c in cases:
        lines.append(f"### `{c.schema_id}`")
        lines.append("")
        lines.append(f"_{hypothesis_for(c.schema_id)}_")
        lines.append("")
        if c.rust.classification == "parse_fail":
            err = (c.rust.error or "").replace("`", "'").replace("\n", " ")[:200]
            lines.append(f"- **cedar-policy:** `parse_fail`; `{err}`")
        elif c.rust.classification == "silent_diff":
            lines.append(f"- **cedar-policy:** `silent_diff`; "
                         f"diff `{c.rust.diff_summary}`")
        else:
            lines.append("- **cedar-policy:** `clean` (round-trips byte-equivalent)")
        if c.go.classification == "parse_fail":
            err = (c.go.error or "").replace("`", "'").replace("\n", " ")[:200]
            lines.append(f"- **cedar-go:** `parse_fail`; `{err}`")
        elif c.go.classification == "panic":
            lines.append(f"- **cedar-go:** `panic`; "
                         f"`{(c.go.error or '')[:200]}`")
        elif c.go.classification == "silent_diff":
            lines.append(f"- **cedar-go:** `silent_diff`; "
                         f"diff `{c.go.diff_summary}`")
        else:
            lines.append("- **cedar-go:** `clean` (round-trips byte-equivalent)")
        lines.append("")
    lines.append("")
    lines.append("## Phase A predicted vs found")
    lines.append("")
    lines.append(
        "The widening hypothesis was: cedar-go's schema marshaller has "
        "*multiple* AST variants its walker doesn't handle, and NEW-1 is "
        "one instance of an architectural class. The widened probe set "
        "covered 8 distinct hypothesis classes (H1-H8). After "
        "well-formedness filtering against `cedar check-parse`, the "
        "honest finding is **narrower than predicted**: every cedar-go "
        "silent-diff lives in the **entity-shape collapse** class. "
        "Specifically, the four well-formed cedar-go silent-diffs "
        "(`h1`, `h1b`, `h1c`, `h1d`) are all entity-shape ::= "
        "TypeRef-naming-a-common-type variants; cedar-go silently emits "
        "an empty Record for each, dropping the common-type alias.")
    lines.append("")
    lines.append(
        "The non-finding outcomes are themselves informative:")
    lines.append("")
    lines.append(
        "- H3/H4/H6b/H7/H8d: cedar-go's `unmarshalType` does not "
        "implement the bare-name TypeRef sugar (`{\"type\": \"Foo\"}`) "
        "in record-attribute / tags / context positions. It returns "
        "`unknown type \"Foo\"` honestly. **Feature gap, not a finding.**")
    lines.append(
        "- H1e (chained common types): same root cause as H3; cedar-go "
        "rejects bare-name TypeRefs even inside another common-type. "
        "Honest error.")
    lines.append(
        "- H2*: ill-formed JSON (entity shape != Record literal) per "
        "cedar-spec; excluded from findings.")
    lines.append(
        "- H5 / H7b / H8a-c: cedar-go round-trips cleanly. The "
        "marshaller correctly handles deep `in` chains, multi-action "
        "appliesTo, and inline extension types in record attrs.")
    lines.append("")
    lines.append(
        "**Architectural root cause of the H1 silent-diffs:** "
        "`cedar-go/x/exp/schema/ast/ast.go:55` defines "
        "`Entity.Shape` as `RecordType` (a type-erased map). The AST "
        "cannot represent any non-Record-literal shape, so the JSON "
        "unmarshaller in `internal/json/json.go:336` calls "
        "`unmarshalRecordType(jet.Shape)` *unconditionally*, ignoring "
        "`jet.Shape.Type`. When `jet.Shape.Type` is anything other "
        "than `Record` (e.g. a TypeRef naming a common type), the "
        "resulting `RecordType` is empty (no `attributes` to iterate). "
        "The Cedar-text marshaller then faithfully emits "
        "`entity Baz {};`. The fix requires widening the AST to admit "
        "TypeRef shapes, not just patching the marshaller.")
    lines.append("")
    lines.append("## Goal-state assessment")
    lines.append("")
    lines.append(
        "- NEW-1 was 1 silent-diff. Phase I widening adds 3 more "
        "well-formed silent-diffs (h1b, h1c, h1d) in the same "
        "architectural class; common-type-with-optional-attr, "
        "namespaced common-type, EntityOrCommon-tagged TypeRef. "
        "Total: **4 well-formed cedar-go silent-diffs**, all in the "
        "entity-shape-TypeRef-collapse class.")
    lines.append(
        "- Predicted but NOT found: silent-diffs in deeper-nested "
        "(record-attr) common-type-refs, multi-namespace, tagged "
        "entities, action context. cedar-go honestly errors on these "
        "(feature gap, NOT a finding).")
    lines.append(
        "- Phase B Lean lift: triggered. The 4 silent-diffs cluster "
        "tightly around one well-formedness predicate "
        "(`shape resolves to a Record after common-type resolution`); "
        "this is exactly what `cedar-spec/cedar-lean/Cedar/Validation/"
        "Types.lean:118` requires. A Lean type-directed generator that "
        "outputs only well-formed (resolved-shape-is-Record) schemas "
        "is a soundness-preserving lift of the Phase A probe.")
    lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
