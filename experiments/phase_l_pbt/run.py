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

# Expected ROOT-level constructor heads, by target. Verified by
# inspection of CedarFull/Expr.lean's genSize cases. `var` is dropped
# from bool/int because the default TypeEnv has no bool/int-typed
# Cedar.Var (principal/action/resource are entities; context is a
# record).
EXPECTED_HEADS = {
    "bool":     {"lit", "and", "or", "ite", "unaryApp", "binaryApp",
                 "hasAttr", "getAttr"},
    "int":      {"lit", "ite", "unaryApp", "binaryApp", "getAttr"},
    "string":   {"lit"},
    "set-bool": {"lit", "set"},   # Stage 3: .set [bool-leaf] arm
    "set-int":  {"lit", "set"},   # Stage 3: .set [int-leaf] arm
    "record":   {"lit", "record"},  # Stage 3: empty .record arm
}

# Expected SUBEXPRESSION heads — these must appear *somewhere* in the
# term tree across the sample, even if never at the root. `.record` is
# reachable via getAttr-of-record-singleton in bool/int branches.
EXPECTED_SUBHEADS = {
    "bool":   {"record"},
    "int":    {"record"},
}

# Edge-case policy ids that must remain reachable in the support.
# These are the 17 policies kept post-Stage 5 because each isolates a
# specific bug class (extension parser drift, record/set edges,
# negation, int-arith, nested attribute) that the random arm does not
# reliably reproduce. Source: cedar-full/CedarFull/PolicyGen.lean
# genPolicy edge-case fixtures.
EDGE_CASE_POLICY_IDS = {
    "permit-when-decimal-eq-self",
    "permit-when-ip-eq-self",
    "permit-when-principal-in-set",
    "permit-when-empty-record-has",
    "permit-when-singleton-record-has",
    "permit-when-principal-has-address",
    "permit-when-nested-attr-eq",
    "permit-when-set-containsAll-self",
    "permit-when-set-contains-principal",
    "permit-when-singleton-contains-principal",
    "permit-when-singleton-in-principal",
    "permit-when-decimal-cross-precision-eq",
    "permit-when-ipv6-eq-self",
    "permit-when-principal-in-empty-set",
    "permit-when-two-key-record-has",
    "permit-when-not-principal-eq-alice",
    "permit-when-int-arith-eq-two",
}

# Stage 5 random-policy generator emits id "random" for every output.
RANDOM_POLICY_ID = "random"

# Expected scope kinds for the random arm. A regression that drops a
# scope variant from genScope would leave one of these missing.
EXPECTED_SCOPE_KINDS_PRINCIPAL = {"any", "eq", "mem", "is", "isMem"}
EXPECTED_SCOPE_KINDS_RESOURCE = {"any", "eq", "mem", "is", "isMem"}
EXPECTED_SCOPE_KINDS_ACTION = {
    "any", "eq", "mem", "is", "isMem", "actionInAny"
}
EXPECTED_CONDITION_KINDS = {"empty", "when", "unless"}


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


def run_genpolicy_sample(n: int) -> list[tuple[str, str, str, str, str, str]]:
    """Sample policies from genPolicy and return per-policy
    (id, principal_scope_kind, action_scope_kind, resource_scope_kind,
     condition_kind, body_repr).

    measure-full doesn't sample policies. We use a one-shot lake script
    that prints tab-separated rows from genPolicy.val (deterministic
    enumeration). The scope kinds let P4 measure scope-shape diversity
    for the random arm; body_repr lets P4 measure random-condition
    body diversity.
    """
    script = """
import CedarFull
open CedarFull
open CedarFull.PolicyGen
def scopeKind : Cedar.Spec.Scope → String
  | .any        => "any"
  | .eq _       => "eq"
  | .mem _      => "mem"
  | .is _       => "is"
  | .isMem _ _  => "isMem"
def actionScopeKind : Cedar.Spec.ActionScope → String
  | .actionScope s    => scopeKind s
  | .actionInAny _    => "actionInAny"
def conditionKind (cs : Cedar.Spec.Conditions) : String :=
  match cs with
  | []      => "empty"
  | c :: _  =>
    match c.kind with
    | .when   => "when"
    | .unless => "unless"
def bodyRepr (cs : Cedar.Spec.Conditions) : String :=
  match cs with
  | []      => "<no-condition>"
  | c :: _  => (reprStr c.body).replace "\\n" " "
def main : IO Unit := do
  let pols := (genPolicy fixedSchema).val
  for p in pols do
    let pK := scopeKind p.principalScope.scope
    let aK := actionScopeKind p.actionScope
    let rK := scopeKind p.resourceScope.scope
    let cK := conditionKind p.condition
    let bR := bodyRepr p.condition
    IO.println s!"{p.id}\\t{pK}\\t{aK}\\t{rK}\\t{cK}\\t{bR}"
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
        rows: list[tuple[str, str, str, str, str, str]] = []
        for line in proc.stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            while len(parts) < 6:
                parts.append("")
            rows.append((parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]))
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
    """Every expected root-level constructor head appears in each
    target's rows; every expected subexpression head appears somewhere
    in the sample's term column for that target."""
    by_target: dict[str, list[tuple[str, str]]] = {}
    for (t, h, _, term) in rows:
        by_target.setdefault(t, []).append((h, term))

    def subreached(target_rows: list[tuple[str, str]], head: str) -> bool:
        token = f"Expr.{head}"
        return any(token in term for _, term in target_rows)

    failures: list[str] = []
    for target, expected_heads in EXPECTED_HEADS.items():
        target_rows = by_target.get(target, [])
        seen_heads = {h for h, _ in target_rows}
        missing = expected_heads - seen_heads
        if missing:
            failures.append(
                f"P2 FAIL ({target} root): missing {sorted(missing)}; "
                f"saw {sorted(seen_heads)}"
            )
    for target, expected_subs in EXPECTED_SUBHEADS.items():
        target_rows = by_target.get(target, [])
        missing = {h for h in expected_subs if not subreached(target_rows, h)}
        if missing:
            failures.append(
                f"P2 FAIL ({target} subterm): missing {sorted(missing)}"
            )

    if failures:
        for f in failures:
            print(f)
        return False

    print(f"P2 OK: all expected root + subterm heads appear across {len(by_target)} targets")
    for target in sorted(by_target):
        c = Counter(h for h, _ in by_target[target])
        print(f"  {target} head freq: {dict(c.most_common())}")
    return True


def property_p3_policy_coverage(
        rows: list[tuple[str, str, str, str, str, str]]) -> bool:
    """Every edge-case policy id must appear in the support, AND the
    random-policy id must appear with substantial cardinality (the
    random arm is the new bulk source). Catches a regression that
    drops an edge-case fixture or unwires genRandomPolicy."""
    ids = [r[0] for r in rows]
    seen = set(ids)
    missing = EDGE_CASE_POLICY_IDS - seen
    if missing:
        print(f"P3 FAIL: missing edge-case policy ids: {sorted(missing)}")
        return False
    if RANDOM_POLICY_ID not in seen:
        print(f"P3 FAIL: random-policy id '{RANDOM_POLICY_ID}' not in support")
        return False
    random_count = sum(1 for pid in ids if pid == RANDOM_POLICY_ID)
    if random_count < 100:
        print(f"P3 FAIL: random-policy count {random_count} < 100; "
              "random arm appears unwired or collapsed")
        return False
    print(f"P3 OK: all {len(EDGE_CASE_POLICY_IDS)} edge-case ids present "
          f"and random-policy count = {random_count}")
    print(f"  total policy ids in support: {len(ids)} ({len(seen)} distinct)")
    return True


# Lower bound on distinct random-arm scope shapes per role and on
# distinct condition bodies. genScope produces 5+ shape variants per
# role × 3 candidate UIDs/types, which yields ≥ 5 distinct kinds.
# genWellTyped at fuel 3 produces ≥ a few dozen distinct bodies.
P4_MIN_DISTINCT_BODIES = 10


def property_p4_random_diversity(
        rows: list[tuple[str, str, str, str, str, str]]) -> bool:
    """Random-arm policies (id == 'random') must exhibit:
       (a) every scope kind in EXPECTED_SCOPE_KINDS_* per role
       (b) every condition kind in EXPECTED_CONDITION_KINDS
       (c) ≥ P4_MIN_DISTINCT_BODIES distinct when/unless bodies
    Catches: scope-arm drop (a), condition-arm drop (b),
             constant-condition (M5-class) regression (c). """
    random_rows = [r for r in rows if r[0] == RANDOM_POLICY_ID]
    if not random_rows:
        print("P4 FAIL: no random-arm rows to inspect")
        return False

    p_kinds = {r[1] for r in random_rows}
    a_kinds = {r[2] for r in random_rows}
    r_kinds = {r[3] for r in random_rows}
    c_kinds = {r[4] for r in random_rows}
    bodies = {r[5] for r in random_rows
              if r[4] in {"when", "unless"} and r[5] != "<no-condition>"}

    failures = []
    miss = EXPECTED_SCOPE_KINDS_PRINCIPAL - p_kinds
    if miss:
        failures.append(f"P4 FAIL principal scope kinds missing: {sorted(miss)}")
    miss = EXPECTED_SCOPE_KINDS_ACTION - a_kinds
    if miss:
        failures.append(f"P4 FAIL action scope kinds missing: {sorted(miss)}")
    miss = EXPECTED_SCOPE_KINDS_RESOURCE - r_kinds
    if miss:
        failures.append(f"P4 FAIL resource scope kinds missing: {sorted(miss)}")
    miss = EXPECTED_CONDITION_KINDS - c_kinds
    if miss:
        failures.append(f"P4 FAIL condition kinds missing: {sorted(miss)}")
    if len(bodies) < P4_MIN_DISTINCT_BODIES:
        failures.append(
            f"P4 FAIL: only {len(bodies)} distinct random when/unless bodies "
            f"(< {P4_MIN_DISTINCT_BODIES}); random-cond arm collapsed")

    if failures:
        for f in failures:
            print(f)
        return False
    print(f"P4 OK: random-arm diversity")
    print(f"  principal scope kinds: {sorted(p_kinds)}")
    print(f"  action scope kinds:    {sorted(a_kinds)}")
    print(f"  resource scope kinds:  {sorted(r_kinds)}")
    print(f"  condition kinds:       {sorted(c_kinds)}")
    print(f"  distinct random bodies: {len(bodies)}")
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
        property_p4_random_diversity(policy_rows),
    ]
    if all(results):
        print("\nALL PROPERTIES PASS")
        return 0
    print("\nFAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
