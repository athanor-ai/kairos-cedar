"""
experiments/phase_j_symcc_sweep/run_symcc.py

Cedar symcc + CVC5 encoder coverage sweep.

Samples N tuples from the 42-shape Lean generator, then feeds each policy
through all applicable cedar symcc subcommands. Captures:
  - VERIFIED  : property holds (exit 0, stdout contains VERIFIED)
  - COUNTEREXAMPLE : property does not hold (exit 0, stdout contains DOES NOT HOLD)
  - PARSE_FAIL / ENCODE_FAIL : pre-CVC5 rejection (exit 1, "Failed to compile"
    or "failed to parse")
  - TIMEOUT   : wall-clock > TIMEOUT_S seconds
  - ERROR     : unexpected failure

Each distinct error message class is an encoder coverage gap.

Usage (inside container via scripts/dc):
    python3 experiments/phase_j_symcc_sweep/run_symcc.py [--n N] [--timeout T]

Or from host:
    ./scripts/dc bash -c 'cd /work && python3 experiments/phase_j_symcc_sweep/run_symcc.py'
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = Path(__file__).resolve().parent
IMAGE = os.environ.get("KAIROS_CEDAR_IMAGE", "ghcr.io/athanor-ai/kairos-cedar:latest")

# Default schema matching the fixed Lean generator schema
FIXED_SCHEMA_TEXT = """\
entity Group;
entity User {
    address: { city: String, street: String, zip: String }
};
entity Document {
    owner: User
};
entity Photo;

action view, edit, admin appliesTo {
    principal: User,
    resource: [Document, Photo],
};
"""

# All three request types (principal-type, action, resource-type)
REQUEST_TYPES = [
    ("User", 'Action::"view"', "Document"),
    ("User", 'Action::"view"', "Photo"),
    ("User", 'Action::"edit"', "Document"),
]

TIMEOUT_S = 30


def run_cmd(cmd: list[str], timeout: int = TIMEOUT_S) -> tuple[int, str, str, float]:
    """Run a command and return (returncode, stdout, stderr, wall_seconds)."""
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.monotonic() - t0
        return proc.returncode, proc.stdout, proc.stderr, elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        return -1, "", "TIMEOUT", elapsed


def run_in_image(cmd: list[str], timeout: int = TIMEOUT_S) -> tuple[int, str, str, float]:
    argv = [
        "docker", "run", "--rm",
        "-v", f"{REPO_ROOT}:/work",
        "-w", "/work",
        IMAGE,
        *cmd,
    ]
    return run_cmd(argv, timeout=timeout)


def is_in_container() -> bool:
    return Path("/.dockerenv").exists() or os.environ.get("container") == "docker"


def sample_tuples(n: int) -> list[dict[str, str]]:
    if is_in_container():
        cmd = ["bash", "-c", f"cd /work/cedar-full && .lake/build/bin/measure-diff {n}"]
        rc, stdout, stderr, _ = run_cmd(cmd, timeout=300)
    else:
        rc, stdout, stderr, _ = run_in_image(
            ["bash", "-c", f"cd /work/cedar-full && .lake/build/bin/measure-diff {n}"],
            timeout=300,
        )
    if rc != 0:
        print(f"ERROR: measure-diff failed (rc={rc}): {stderr[-500:]}", file=sys.stderr)
        return []

    tuples = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        idx, principal, action, resource = parts[0], parts[1], parts[2], parts[3]
        policy_text = "\t".join(parts[4:])
        # Extract entity types from UIDs  e.g. "User::alice" -> "User"
        principal_type = principal.split("::")[0] if "::" in principal else principal
        action_uid = action  # e.g. "Action::view" -> for cedar symcc we need Action::"view"
        resource_type = resource.split("::")[0] if "::" in resource else resource
        # Fix action format: "Action::view" -> 'Action::"view"'
        action_fixed = re.sub(r"(\w+)::(\w+)", lambda m: f'{m.group(1)}::"{m.group(2)}"', action_uid)
        tuples.append({
            "idx": idx,
            "principal_type": principal_type,
            "action": action_fixed,
            "resource_type": resource_type,
            "policy": policy_text,
        })
    return tuples


def classify_output(rc: int, stdout: str, stderr: str, elapsed: float) -> tuple[str, str]:
    """Returns (category, detail) for a symcc invocation."""
    if elapsed >= TIMEOUT_S:
        return "TIMEOUT", "wall-clock timeout"

    combined = stdout + stderr

    if rc == 0:
        if "VERIFIED" in combined:
            return "VERIFIED", ""
        if "DOES NOT HOLD" in combined:
            # Extract first line of counterexample
            ce_lines = [l for l in combined.splitlines() if l.strip() and "DOES NOT HOLD" not in l and "Counterexample" not in l]
            ce_head = ce_lines[0].strip() if ce_lines else ""
            return "COUNTEREXAMPLE", ce_head
        return "UNKNOWN_RC0", combined[:200]

    if rc == 1:
        if "Failed to compile policy" in combined:
            # Extract the specific error message
            m = re.search(r"Failed to compile policy:[^\[]*\[(\w+)\(", combined)
            if m:
                return "ENCODE_FAIL", m.group(1)
            return "ENCODE_FAIL", combined[:200]
        if "failed to parse policy set" in combined or "failed to parse" in combined:
            return "PARSE_FAIL", combined[:200]
        if "Expected exactly one policy" in combined:
            return "SINGLE_POLICY_REQUIRED", combined[:100]
        if "action not found in schema" in combined:
            return "SCHEMA_ACTION_NOT_FOUND", combined[:100]
        if "Analysis failed" in combined:
            # Generic analysis failure - extract the message
            m = re.search(r"Analysis failed:.*?×\s*(.+)", combined, re.DOTALL)
            msg = m.group(1)[:150] if m else combined[:150]
            return "ANALYSIS_FAIL", msg.strip()
        return "ERROR", combined[:200]

    if rc == -1:
        return "TIMEOUT", "wall-clock timeout"

    return "ERROR", f"rc={rc}: {combined[:200]}"


def run_symcc(
    policy_text: str,
    subcommand: str,
    principal_type: str,
    action: str,
    resource_type: str,
    schema_text: str,
    extra_policy_text: str = "",
    timeout: int = TIMEOUT_S,
) -> tuple[str, str, float]:
    """
    Run cedar symcc with a given subcommand on the provided policy text.
    Returns (category, detail, elapsed).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        schema_file = tmppath / "schema.cedarschema"
        schema_file.write_text(schema_text)
        pol_file = tmppath / "policy.cedar"
        pol_file.write_text(policy_text)

        base_cmd = [
            "cedar", "symcc",
            "--principal-type", principal_type,
            "--action", action,
            "--resource-type", resource_type,
            "--schema", str(schema_file),
            subcommand,
        ]

        # Single-policy subcommands
        single_policy_cmds = {
            "never-errors": ["--policies", str(pol_file)],
            "always-matches": ["--policies", str(pol_file)],
            "never-matches": ["--policies", str(pol_file)],
        }
        # Multi-policy subcommands (same policy set compared to itself or empty)
        multi_policy_cmds = {
            "always-allows": ["--policies", str(pol_file)],
            "always-denies": ["--policies", str(pol_file)],
        }
        # Two-policy-set subcommands
        comparison_cmds_polsets = {
            "equivalent": ["--policies1", str(pol_file), "--policies2", str(pol_file)],
            "implies": ["--policies1", str(pol_file), "--policies2", str(pol_file)],
            "disjoint": ["--policies1", str(pol_file), "--policies2", str(pol_file)],
        }
        # Two individual-policy subcommands
        comparison_cmds_singles = {
            "matches-equivalent": ["--policy1", str(pol_file), "--policy2", str(pol_file)],
            "matches-implies": ["--policy1", str(pol_file), "--policy2", str(pol_file)],
            "matches-disjoint": ["--policy1", str(pol_file), "--policy2", str(pol_file)],
        }

        if subcommand in single_policy_cmds:
            full_cmd = base_cmd + single_policy_cmds[subcommand]
        elif subcommand in multi_policy_cmds:
            full_cmd = base_cmd + multi_policy_cmds[subcommand]
        elif subcommand in comparison_cmds_polsets:
            full_cmd = base_cmd + comparison_cmds_polsets[subcommand]
        elif subcommand in comparison_cmds_singles:
            full_cmd = base_cmd + comparison_cmds_singles[subcommand]
        else:
            return "ERROR", f"unknown subcommand: {subcommand}", 0.0

        if is_in_container():
            rc, stdout, stderr, elapsed = run_cmd(full_cmd, timeout=timeout)
        else:
            rc, stdout, stderr, elapsed = run_in_image(full_cmd, timeout=timeout)

        cat, detail = classify_output(rc, stdout, stderr, elapsed)
        return cat, detail, elapsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=1000, help="Number of tuples to sample")
    parser.add_argument("--timeout", type=int, default=TIMEOUT_S, help="Per-invocation timeout (s)")
    args = parser.parse_args()

    n = args.n
    timeout = args.timeout

    print(f"Sampling {n} tuples from measure-diff...", flush=True)
    tuples = sample_tuples(n)
    if not tuples:
        print("ERROR: no tuples sampled", file=sys.stderr)
        sys.exit(1)
    print(f"Got {len(tuples)} tuples", flush=True)

    # Subcommands to test for each tuple
    single_subcommands = ["never-errors", "always-matches", "never-matches"]
    multi_subcommands = ["always-allows", "always-denies"]
    pair_singles = ["matches-equivalent", "matches-implies", "matches-disjoint"]
    pair_sets = ["equivalent", "implies", "disjoint"]

    all_subcommands = (
        single_subcommands
        + multi_subcommands
        + pair_singles
        + pair_sets
    )

    # Count outcomes
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # Track distinct error details for gap analysis
    error_classes: dict[str, set[str]] = defaultdict(set)
    # Track examples for each error class
    error_examples: dict[str, list[dict]] = defaultdict(list)
    # All results for JSON dump
    results = []

    total_invocations = 0
    t_start = time.monotonic()

    for i, tup in enumerate(tuples):
        policy = tup["policy"]
        pt = tup["principal_type"]
        act = tup["action"]
        rt = tup["resource_type"]

        for subcommand in all_subcommands:
            total_invocations += 1
            cat, detail, elapsed = run_symcc(
                policy_text=policy,
                subcommand=subcommand,
                principal_type=pt,
                action=act,
                resource_type=rt,
                schema_text=FIXED_SCHEMA_TEXT,
                timeout=timeout,
            )
            counts[subcommand][cat] += 1
            if cat not in ("VERIFIED", "COUNTEREXAMPLE"):
                error_classes[cat].add(detail[:80])
                if len(error_examples[f"{cat}::{detail[:40]}"]  ) < 3:
                    error_examples[f"{cat}::{detail[:40]}"].append({
                        "subcommand": subcommand,
                        "policy": policy,
                        "principal_type": pt,
                        "action": act,
                        "resource_type": rt,
                        "detail": detail,
                    })

            results.append({
                "tuple_idx": tup["idx"],
                "subcommand": subcommand,
                "category": cat,
                "detail": detail,
                "elapsed": round(elapsed, 3),
                "policy": policy,
                "principal_type": pt,
                "action": act,
                "resource_type": rt,
            })

        if (i + 1) % 50 == 0:
            elapsed_total = time.monotonic() - t_start
            rate = total_invocations / elapsed_total if elapsed_total > 0 else 0
            print(
                f"  {i+1}/{len(tuples)} tuples, {total_invocations} invocations, "
                f"{elapsed_total:.1f}s elapsed ({rate:.1f}/s)",
                flush=True,
            )

    elapsed_total = time.monotonic() - t_start
    print(f"\nCompleted {total_invocations} invocations in {elapsed_total:.1f}s", flush=True)

    # Write raw results
    results_path = RESULTS_DIR / "results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results written to {results_path}", flush=True)

    # Print summary table
    print("\n=== OUTCOME SUMMARY BY SUBCOMMAND ===")
    all_cats = sorted({cat for d in counts.values() for cat in d})
    header = f"{'subcommand':<22}" + "".join(f"  {c[:14]:<14}" for c in all_cats)
    print(header)
    print("-" * len(header))
    for sub in all_subcommands:
        row = f"{sub:<22}" + "".join(
            f"  {counts[sub].get(c, 0):<14}" for c in all_cats
        )
        print(row)

    print("\n=== ENCODER GAP CLASSES ===")
    for cat, details in error_classes.items():
        if cat in ("VERIFIED", "COUNTEREXAMPLE"):
            continue
        print(f"\n{cat}:")
        for d in sorted(details):
            print(f"  - {d}")

    print("\n=== EXAMPLE INPUTS FOR EACH GAP CLASS ===")
    for key, examples in error_examples.items():
        print(f"\n{key}:")
        for ex in examples[:2]:
            print(f"  subcommand={ex['subcommand']}, policy={ex['policy'][:80]}")
            print(f"  detail={ex['detail'][:80]}")


if __name__ == "__main__":
    main()
