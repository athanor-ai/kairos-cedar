#!/usr/bin/env python3
"""
phase_l_pbt: property-based-testing harness for cedar-full's generator.

Runs three properties against a sampled prefix of CedarFull.genWellTyped:

  P1 (soundness empirical check):
        every sampled expression has wellTypedAt = True
        (The Lean theorem already proves this; the empirical check is
        a regression net — if a refactor breaks the proof's invariant
        but slips past the kernel, the runtime sample exposes it.)

  P2 (constructor coverage):
        every constructor head in the EXPECTED_HEADS set appears in
        the bool / int sampled prefix at least once. A regression that
        drops an arm reduces the head set; this property fails closed.

  P3 (random-condition policy coverage):
        every policy id in the RANDOM_CONDITION_POLICY_IDS set is
        emitted by at least one sample of CedarFull.genTuple. Catches
        the "PolicyGen drops a random shape" class of regression.

Usage:
    ./scripts/dc python3 experiments/phase_l_pbt/run.py [--n N] [--seed S]

Exit codes:
    0  all properties hold
    1  at least one property failed (counterexamples printed)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CEDAR_FULL = REPO / "cedar-full"

# Expected ROOT-level constructor heads at the bool / int targets after
# Stages 1+2. Verified by inspection of CedarFull/Expr.lean's genSize
# cases. The `.record` constructor IS exercised (as the inner subexpr
# of getAttr-of-record-singleton), but never appears at the root —
# generation at type `.record _` is deferred to Stage 3. Same for
# `.set` and `.call`. `var` is dropped because the default TypeEnv has
# no bool/int-typed Cedar.Var (principal/action/resource are entities;
# context is a record).
EXPECTED_HEADS_BOOL = {
    "lit", "and", "or", "ite", "unaryApp", "binaryApp",
    "hasAttr", "getAttr",
}
EXPECTED_HEADS_INT = {
    "lit", "ite", "unaryApp", "binaryApp", "getAttr",
}

# Expected SUBEXPRESSION heads — these must appear *somewhere* in the
# term tree across the sample, even if never at the root. The presence
# of these establishes the genSize compounds reach into less-common
# constructors. `.record` is reachable via getAttr-of-record-singleton.
EXPECTED_SUBHEADS_BOOL = {"record"}
EXPECTED_SUBHEADS_INT = {"record"}

# Five random-condition policy ids wired into PolicyGen.genPolicy.
# Source: cedar-full/CedarFull/PolicyGen.lean shapes 43-47.
RANDOM_CONDITION_POLICY_IDS = {
    "permit-with-when-cond",
    "permit-with-unless-cond",
    "forbid-with-when-cond",
    "forbid-with-unless-cond",
    "permit-principal-is-user-with-when-cond",
}


def run_measure(n: int) -> list[tuple[str, str, str, str]]:
    """Run measure-full and return [(target, head, wt, term), ...]."""
    proc = subprocess.run(
        ["lake", "exe", "measure-full", str(n)],
        cwd=str(CEDAR_FULL),
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode != 0:
        print("measure-full exited non-zero:", proc.returncode, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        sys.exit(2)
    rows: list[tuple[str, str, str, str]] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 3)
        if len(parts) != 4:
            continue
        rows.append((parts[0], parts[1], parts[2], parts[3]))
    return rows


def run_genpolicy_sample(n: int) -> list[tuple[str, str]]:
    """Sample policies from genPolicy and return [(id, body_repr), ...].

    measure-full doesn't sample policies. We use a one-shot lake script
    that prints policy id + condition-body repr from genPolicy.val
    (deterministic enumeration). The body_repr lets P4 measure
    random-condition body diversity per shape.
    """
    script = """
import CedarFull
open CedarFull
open CedarFull.PolicyGen
def bodyRepr (p : Cedar.Spec.Policy) : String :=
  match p.condition.head? with
  | some c => (reprStr c.body).replace "\\n" " "
  | none   => "<no-condition>"
def main : IO Unit := do
  let pols := (genPolicy fixedSchema).val
  for p in pols do
    IO.println s!"{p.id}\\t{bodyRepr p}"
"""
    script_path = CEDAR_FULL / ".pbt_genpolicy_ids.lean"
    script_path.write_text(script)
    try:
        proc = subprocess.run(
            ["lake", "env", "lean", "--run", str(script_path)],
            cwd=str(CEDAR_FULL),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if proc.returncode != 0:
            print("genpolicy sample exited non-zero:", proc.returncode, file=sys.stderr)
            print(proc.stderr, file=sys.stderr)
            sys.exit(2)
        rows: list[tuple[str, str]] = []
        for line in proc.stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                rows.append((parts[0], parts[1]))
            else:
                rows.append((parts[0], ""))
        return rows
    finally:
        if script_path.exists():
            script_path.unlink()


def property_p1_empirical_soundness(rows: list[tuple[str, str, str, str]]) -> bool:
    """Every sample must have wellTypedAt = true."""
    bad = [(t, h, term) for (t, h, wt, term) in rows if wt.lower() != "true"]
    if bad:
        print(f"P1 FAIL: {len(bad)} of {len(rows)} samples have wellTypedAt = false")
        for t, h, term in bad[:5]:
            print(f"  target={t} head={h} term={term[:120]}")
        return False
    print(f"P1 OK: all {len(rows)} sampled exprs have wellTypedAt = true")
    return True


def property_p2_constructor_coverage(rows: list[tuple[str, str, str, str]]) -> bool:
    """Every expected root-level constructor head appears in the bool / int
    rows; every expected subexpression head appears somewhere in the
    sample's term column."""
    bool_rows = [(h, term) for (t, h, _, term) in rows if t == "bool"]
    int_rows = [(h, term) for (t, h, _, term) in rows if t == "int"]
    bool_heads = {h for h, _ in bool_rows}
    int_heads = {h for h, _ in int_rows}

    missing_bool = EXPECTED_HEADS_BOOL - bool_heads
    missing_int = EXPECTED_HEADS_INT - int_heads

    # Subexpression search: a head h is "subreachable" in target t if
    # `Expr.h ` (with trailing space, the reprStr token shape) appears
    # anywhere in any term string for that target. Conservative —
    # may false-positive on a constructor name embedded in a string
    # literal, but no Cedar grammar produces "Expr.h" inside a string.
    def subreached(rows_for_target: list[tuple[str, str]], head: str) -> bool:
        token = f"Expr.{head}"
        return any(token in term for _, term in rows_for_target)

    missing_subbool = {h for h in EXPECTED_SUBHEADS_BOOL
                       if not subreached(bool_rows, h)}
    missing_subint = {h for h in EXPECTED_SUBHEADS_INT
                      if not subreached(int_rows, h)}

    failures = []
    if missing_bool:
        failures.append(f"P2 FAIL (bool root): missing {sorted(missing_bool)}; "
                        f"saw {sorted(bool_heads)}")
    if missing_int:
        failures.append(f"P2 FAIL (int root): missing {sorted(missing_int)}; "
                        f"saw {sorted(int_heads)}")
    if missing_subbool:
        failures.append(f"P2 FAIL (bool subterm): missing {sorted(missing_subbool)}")
    if missing_subint:
        failures.append(f"P2 FAIL (int subterm): missing {sorted(missing_subint)}")

    if failures:
        for f in failures:
            print(f)
        return False

    bool_count = Counter(h for h, _ in bool_rows)
    int_count = Counter(h for h, _ in int_rows)
    print(f"P2 OK: all expected root + subterm heads appear")
    print(f"  bool head freq: {dict(bool_count.most_common())}")
    print(f"  int  head freq: {dict(int_count.most_common())}")
    return True


def property_p3_policy_coverage(rows: list[tuple[str, str]]) -> bool:
    """Every random-condition policy id must appear in the sample."""
    ids = [pid for pid, _ in rows]
    seen = set(ids)
    missing = RANDOM_CONDITION_POLICY_IDS - seen
    if missing:
        print(f"P3 FAIL: missing random-condition policy ids: {sorted(missing)}")
        print(f"   ids seen: {sorted(seen)}")
        return False
    rc_count = Counter(p for p in ids if p in RANDOM_CONDITION_POLICY_IDS)
    print(f"P3 OK: all 5 random-condition policy ids appear")
    print(f"  random-condition freq: {dict(rc_count.most_common())}")
    print(f"  total policy ids in support: {len(ids)} ({len(seen)} distinct)")
    return True


# Lower bound on distinct condition bodies expected for each
# random-condition policy shape. genWellTyped at fuel 3 produces
# ≥ a few hundred distinct exprs at .bool .anyBool, so each shape
# wired through `do let condExpr ← genWellTyped …` should pull at
# least this many distinct bodies. A constant-condition mutation
# (M5 in phase_m_mutation) collapses this to 1, failing P4.
P4_MIN_DISTINCT_BODIES_PER_SHAPE = 10


def property_p4_random_cond_body_diversity(
        rows: list[tuple[str, str]]) -> bool:
    """Each random-condition policy shape must produce more than
    P4_MIN_DISTINCT_BODIES_PER_SHAPE distinct condition bodies.
    A regression that replaces `do let condExpr ← genWellTyped …`
    with a constant or a single literal collapses the body set
    and trips this check."""
    bodies_by_id: dict[str, set[str]] = {}
    for pid, body in rows:
        if pid not in RANDOM_CONDITION_POLICY_IDS:
            continue
        bodies_by_id.setdefault(pid, set()).add(body)

    failures = []
    for pid in RANDOM_CONDITION_POLICY_IDS:
        n = len(bodies_by_id.get(pid, set()))
        if n < P4_MIN_DISTINCT_BODIES_PER_SHAPE:
            failures.append((pid, n))

    if failures:
        for pid, n in failures:
            print(f"P4 FAIL: shape '{pid}' has only {n} distinct condition "
                  f"bodies (< {P4_MIN_DISTINCT_BODIES_PER_SHAPE})")
        print("  This is the M5-class regression: a random-condition arm was "
              "replaced with a constant or non-genWellTyped expression.")
        return False
    print(f"P4 OK: every random-condition shape has "
          f"≥{P4_MIN_DISTINCT_BODIES_PER_SHAPE} distinct bodies")
    for pid in sorted(RANDOM_CONDITION_POLICY_IDS):
        print(f"  {pid}: {len(bodies_by_id.get(pid, set()))} distinct bodies")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200,
                    help="number of expr samples per target (bool/int/string)")
    args = ap.parse_args()

    print(f"Sampling {args.n} expressions per target via measure-full ...")
    rows = run_measure(args.n)
    print(f"  -> {len(rows)} rows total")

    print("Sampling genPolicy ids + bodies via lake one-shot ...")
    policy_rows = run_genpolicy_sample(args.n)
    print(f"  -> {len(policy_rows)} policies in support")

    results = [
        property_p1_empirical_soundness(rows),
        property_p2_constructor_coverage(rows),
        property_p3_policy_coverage(policy_rows),
        property_p4_random_cond_body_diversity(policy_rows),
    ]
    if all(results):
        print("\nALL PROPERTIES PASS")
        return 0
    print("\nFAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
