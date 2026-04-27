#!/usr/bin/env python3
"""
phase_m_mutation: mutation-test harness for cedar-full.

We claim the cedar-full Lean tests + PBT runner cover the generator
arms and policy templates. Mutation testing verifies that claim: for
each known-bad mutation we apply, at least one test must fail.

The harness:
  1. Reads a list of mutations (sed-style edits on Expr.lean / PolicyGen.lean
     / Soundness.lean, applied as a single text substitution).
  2. For each mutation:
     a. Applies the mutation in-place.
     b. Runs `lake build` (which kernel-checks Test.lean's `decide`/`rfl`
        obligations).
     c. Runs the PBT harness (phase_l_pbt) if `lake build` survives.
     d. Reports KILLED (build or PBT failed = test caught the mutation)
        or LIVED (no test failed = the mutation slipped through, gap in
        the test suite).
     e. Restores the original file content.
  3. Reports a kill rate. Mutation kills are good (test caught
     regression); lived mutations are gaps to file as follow-ups.

Usage:
    ./scripts/dc python3 experiments/phase_m_mutation/run.py [--n N] [--quiet]

Exit codes:
    0  all mutations killed
    1  at least one mutation lived (test gap)
    2  harness internal error
"""
from __future__ import annotations

import argparse
import dataclasses
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CEDAR_FULL = REPO / "cedar-full"

# Detect whether we're already inside the kairos-cedar container.
# Inside, subprocess calls run lake/python directly. Outside, we
# wrap each call in ./scripts/dc so it lands in the container.
INSIDE_CONTAINER = Path("/work/cedar-full").exists()
CONTAINER_CEDAR_FULL = Path("/work/cedar-full")


@dataclasses.dataclass
class Mutation:
    """One text-substitution mutation on a single source file.

    The harness reads the file, replaces `find` with `replace` exactly
    once (asserts uniqueness), and writes back. After the test cycle,
    the original content is restored byte-exact.
    """
    name: str
    file: Path
    find: str
    replace: str
    expected_failure_in: str  # "lake-build" or "pbt"
    rationale: str


# ── The mutation set ────────────────────────────────────────────────
# Each mutation is a known-bad change. The test layer named in
# expected_failure_in must fail for the mutation to be "killed".

MUTATIONS: list[Mutation] = [
    Mutation(
        name="M1_drop_hasAttr_arm",
        file=CEDAR_FULL / "CedarFull/Expr.lean",
        find='      genHasAttrContext\n      -- getAttr (.record [("v", a)]) "v" with a a bool literal:',
        replace='      (pure (.lit (.bool false)))\n      -- getAttr (.record [("v", a)]) "v" with a a bool literal:',
        expected_failure_in="lake-build",
        rationale="Replace genHasAttrContext arm with a constant bool lit. "
                  "Test.lean's hasAttr-in-genSize obligation must fail.",
    ),
    Mutation(
        name="M2_drop_unless_cond_template",
        file=CEDAR_FULL / "CedarFull/PolicyGen.lean",
        find='def policyWithUnlessCond (condExpr : Expr) : Policy :=\n  { id             := "permit-with-unless-cond"',
        replace='def policyWithUnlessCond (condExpr : Expr) : Policy :=\n  { id             := "permit-with-RENAMED-cond"',
        expected_failure_in="lake-build",
        rationale="Rename id of policyWithUnlessCond. Test.lean's "
                  "structural id-eq obligation must fail.",
    ),
    Mutation(
        name="M3_swap_when_to_unless_in_forbid",
        file=CEDAR_FULL / "CedarFull/PolicyGen.lean",
        find='def forbidPolicyWithWhenCond (condExpr : Expr) : Policy :=\n  { id             := "forbid-with-when-cond"\n  , effect         := .forbid\n  , principalScope := .principalScope .any\n  , actionScope    := .actionScope .any\n  , resourceScope  := .resourceScope .any\n  , condition      := [{ kind := .when, body := condExpr }]\n  }',
        replace='def forbidPolicyWithWhenCond (condExpr : Expr) : Policy :=\n  { id             := "forbid-with-when-cond"\n  , effect         := .forbid\n  , principalScope := .principalScope .any\n  , actionScope    := .actionScope .any\n  , resourceScope  := .resourceScope .any\n  , condition      := [{ kind := .unless, body := condExpr }]\n  }',
        expected_failure_in="lake-build",
        rationale="Flip kind=.when to kind=.unless inside forbid-with-when-cond template. "
                  "Test.lean's condition.kind obligation must fail.",
    ),
    Mutation(
        name="M4_drop_hasAttr_name_from_list",
        file=CEDAR_FULL / "CedarFull/Expr.lean",
        find='def hasAttrNames : List String :=\n  ["approved", "tags", "name", "level", "id"]',
        replace='def hasAttrNames : List String :=\n  ["approved", "tags", "name", "level"]',
        expected_failure_in="lake-build",
        rationale='Remove "id" from hasAttrNames. Test.lean\'s length=5 and '
                  '"id" ∈ hasAttrNames obligations must both fail.',
    ),
    Mutation(
        name="M5_swap_random_cond_to_constant",
        file=CEDAR_FULL / "CedarFull/PolicyGen.lean",
        find="(do let condExpr ← genWellTyped fixedEnv (.bool .anyBool)\n                  pure (policyWithIsUserAndWhenCond condExpr))",
        replace="(pure (policyWithIsUserAndWhenCond (.lit (.bool true))))",
        expected_failure_in="pbt",
        rationale="Replace genWellTyped-bound condExpr with a constant true. "
                  "lake-build passes (template structure unchanged); PBT P3 "
                  "passes (id stays reachable, just with reduced count); "
                  "PBT P4 fails because the affected shape collapses from "
                  "27+ distinct bodies to 1, which is below the diversity "
                  "threshold (P4_MIN_DISTINCT_BODIES_PER_SHAPE).",
    ),
]


def run_lake_build(quiet: bool = False) -> tuple[bool, str]:
    """Returns (success, log_tail).

    `set -o pipefail` is essential: without it the trailing `| tail -30`
    masks lake's non-zero exit and every mutation looks killed.
    """
    if INSIDE_CONTAINER:
        cmd = ["bash", "-c",
               "set -o pipefail; cd /work/cedar-full && lake build 2>&1 | tail -30"]
        cwd = "/work"
    else:
        cmd = ["./scripts/dc", "bash", "-c",
               "set -o pipefail; cd /work/cedar-full && lake build 2>&1 | tail -30"]
        cwd = str(REPO)
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=600,
    )
    if not quiet and proc.returncode != 0:
        print(f"  [build rc={proc.returncode}]")
        print(f"  [stderr]: {proc.stderr[:300]}")
        tail = proc.stdout.strip().splitlines()[-4:]
        print("  [stdout tail]: " + " | ".join(tail))
    return proc.returncode == 0, proc.stdout


def run_pbt(n: int, quiet: bool = False) -> tuple[bool, str]:
    """Returns (success, log_tail)."""
    if INSIDE_CONTAINER:
        cmd = ["python3", "experiments/phase_l_pbt/run.py", "--n", str(n)]
        cwd = "/work"
    else:
        cmd = ["./scripts/dc", "python3", "experiments/phase_l_pbt/run.py",
               "--n", str(n)]
        cwd = str(REPO)
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=600,
    )
    return proc.returncode == 0, proc.stdout


def apply_mutation(m: Mutation) -> str:
    """Apply mutation to file. Returns the original file content for restoration.

    Asserts the `find` string appears exactly once in the file (else the
    mutation is ambiguous and the harness aborts).
    """
    if not m.file.exists():
        raise FileNotFoundError(m.file)
    original = m.file.read_text()
    occurrences = original.count(m.find)
    if occurrences == 0:
        raise ValueError(f"{m.name}: find-string not present in {m.file}")
    if occurrences > 1:
        raise ValueError(
            f"{m.name}: find-string appears {occurrences} times in {m.file}; "
            "mutation is ambiguous"
        )
    mutated = original.replace(m.find, m.replace, 1)
    m.file.write_text(mutated)
    return original


def restore(m: Mutation, original: str) -> None:
    m.file.write_text(original)


def cycle_one(m: Mutation, n: int, quiet: bool) -> tuple[bool, str]:
    """Apply m, run tests, restore, return (killed?, why)."""
    original = apply_mutation(m)
    try:
        build_ok, build_log = run_lake_build(quiet=quiet)
        if m.expected_failure_in == "lake-build":
            if not build_ok:
                return True, "lake build failed (expected)"
            return False, ("lake build SURVIVED unexpectedly. "
                           "Last 6 log lines: " +
                           "\n".join(build_log.strip().splitlines()[-6:]))
        # expected_failure_in == "pbt"
        if not build_ok:
            return True, ("lake build failed before reaching PBT — "
                          "still a kill, but the mutation is stronger "
                          "than scoped")
        pbt_ok, pbt_log = run_pbt(n, quiet=quiet)
        if not pbt_ok:
            return True, "PBT failed (expected)"
        return False, "PBT SURVIVED — gap in test suite"
    finally:
        restore(m, original)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200,
                    help="PBT sample size per target — N must be large enough "
                         "that low-frequency arms (getAttr, hasAttr) appear "
                         "reliably; empirically ≥200 is stable, <100 flakes.")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--only", action="append",
                    help="run only mutations whose name contains this substring; "
                         "may be passed multiple times")
    args = ap.parse_args()

    selected = [m for m in MUTATIONS
                if not args.only or any(s in m.name for s in args.only)]
    print(f"Running {len(selected)} mutations against cedar-full")
    print("-" * 72)

    results: list[tuple[Mutation, bool, str, float]] = []
    for m in selected:
        print(f"[{m.name}] applying ...")
        t0 = time.monotonic()
        try:
            killed, reason = cycle_one(m, args.n, args.quiet)
        except Exception as exc:
            print(f"  HARNESS ERROR: {exc}")
            return 2
        elapsed = time.monotonic() - t0
        outcome = "KILLED" if killed else "LIVED"
        print(f"  {outcome} ({elapsed:.0f}s)  {reason}")
        results.append((m, killed, reason, elapsed))

    print("-" * 72)
    killed = sum(1 for _, k, _, _ in results if k)
    lived = len(results) - killed
    rate = killed / len(results) * 100 if results else 0.0
    print(f"Mutation kill rate: {killed}/{len(results)} = {rate:.0f}%")
    if lived:
        print("\nLived mutations (test gaps):")
        for m, k, reason, _ in results:
            if not k:
                print(f"  {m.name}: {reason}")
                print(f"    rationale: {m.rationale}")

    return 0 if lived == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
