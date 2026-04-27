"""
experiments/phase_k_opa_diff/run_opa_diff.py  — OPA/Rego differential test runner.

Takes the Lean spec's decisions (from `lake exec measure-rego` in rego-full/)
and validates each policy+input pair against OPA's Go reference implementation.

Emits a summary: agreement rate, disagreements, and any bugs found.

Usage:
    python3 experiments/phase_k_opa_diff/run_opa_diff.py [--n N] [--opa OPA_PATH]

Spec source: rego-full/MeasureRego.lean (via `lake exec measure-rego`).
OPA binary: downloaded from GitHub releases or passed via --opa.

Output format:
    AGREE    shape  input  spec_result   opa_result
    DISAGREE shape  input  spec_result   opa_result   [BUG]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REGO_FULL = REPO_ROOT / "rego-full"

# Default OPA binary location (downloaded to /tmp for the run)
DEFAULT_OPA = "/tmp/opa"


# ─── Data ──────────────────────────────────────────────────────────────────────

class Tuple(NamedTuple):
    shape_name: str
    input_name: str
    spec_result: str     # "true" | "false" | "undefined"
    policy_rego: str
    input_json: str


class Result(NamedTuple):
    t: Tuple
    opa_result: str       # "true" | "false" | "undefined" | "error:<msg>"
    agreed: bool


# ─── Lean driver ───────────────────────────────────────────────────────────────

def run_lean_driver() -> list[Tuple]:
    """Run `lake exec measure-rego` and parse tab-separated output."""
    proc = subprocess.run(
        ["lake", "exec", "measure-rego"],
        cwd=REGO_FULL,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        print(f"[ERROR] lake exec measure-rego failed:\n{proc.stderr}", file=sys.stderr)
        sys.exit(1)

    tuples = []
    for line in proc.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        shape_name, input_name, spec_result = parts[0], parts[1], parts[2]
        # Unescape \n back to real newlines (we escape them for single-line TSV)
        policy_rego = parts[3].replace("\\n", "\n")
        input_json = parts[4]
        tuples.append(Tuple(shape_name, input_name, spec_result, policy_rego, input_json))
    return tuples


# ─── OPA runner ────────────────────────────────────────────────────────────────

def run_opa(opa_path: str, policy_rego: str, input_json: str) -> str:
    """Run OPA and return 'true', 'false', 'undefined', or 'error:<msg>'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        policy_file = os.path.join(tmpdir, "policy.rego")
        input_file  = os.path.join(tmpdir, "input.json")

        with open(policy_file, "w") as f:
            f.write(policy_rego)
        with open(input_file, "w") as f:
            f.write(input_json)

        try:
            proc = subprocess.run(
                [opa_path, "eval",
                 "--data", policy_file,
                 "--input", input_file,
                 "--format", "json",
                 "data.kairos.allow"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return "error:timeout"

        if proc.returncode not in (0, 1):
            # Exit code 2 = error in OPA itself
            stderr = proc.stderr.strip()[:200]
            return f"error:{stderr}"

        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            return f"error:json_parse:{e}"

        # OPA result structure: {"result": [{"expressions": [{"value": ...}]}]}
        # Empty result = {} or {"result": []} means undefined.
        if not out or not out.get("result"):
            return "undefined"

        expressions = out["result"][0].get("expressions", [])
        if not expressions:
            return "undefined"

        value = expressions[0].get("value")
        if value is True:
            return "true"
        elif value is False:
            return "false"
        elif value is None:
            return "undefined"
        else:
            return f"error:unexpected_value:{value!r}"


# ─── Disagreement classification ───────────────────────────────────────────────

def classify_disagreement(t: Tuple, opa_result: str) -> str:
    """Classify a disagreement and return a bug label."""
    spec = t.spec_result
    opa  = opa_result

    if spec == "true" and opa == "false":
        return "BUG: spec says ALLOW, OPA says DENY"
    if spec == "false" and opa == "true":
        return "BUG: spec says DENY, OPA says ALLOW"
    if spec == "undefined" and opa == "true":
        return "BUG: spec says UNDEFINED, OPA says ALLOW"
    if spec == "undefined" and opa == "false":
        # OPA may return false for undefined-but-denied; this is a spec-violation
        # if OPA's spec says undefined ≠ false.
        return "POSSIBLE-BUG: spec says UNDEFINED, OPA returns false (undefined vs false conflation)"
    if spec == "true" and opa == "undefined":
        return "BUG: spec says ALLOW, OPA says UNDEFINED"
    if spec == "false" and opa == "undefined":
        # This can be legitimate in Rego: false = undefined for completed rules.
        # But if our spec says false, OPA should agree.
        return "POSSIBLE-BUG: spec says DENY(false), OPA says UNDEFINED"
    if opa.startswith("error:"):
        return f"OPA-ERROR: {opa}"
    return f"UNEXPECTED-DISAGREEMENT: spec={spec} opa={opa}"


# ─── Main ──────────────────────────────────────────────────────────────────────

def make_extended_tuples() -> list[Tuple]:
    """Extended tuples that specifically probe the spec-vs-OPA semantic gaps.

    These are NOT in the Lean generator's output because they require
    inputs that violate the schema (object instead of array, missing fields).
    They are added here to demonstrate the bugs found via manual analysis.
    """
    shape7_policy = (
        "package kairos\n\n"
        "allow if {\n"
        "    not (input.active == true)\n"
        "    input.role == \"viewer\"\n"
        "}\n"
    )
    shape6_policy = (
        "package kairos\n\n"
        "allow if {\n"
        "    input.groups[_] == \"ops\"\n"
        "}\n"
    )

    return [
        # Bug 1: NAF - not(undefined) = undefined in spec, but true in OPA
        Tuple(
            shape_name="not-active-and-role-viewer",
            input_name="EXTENDED:active-missing",
            spec_result="undefined",    # strict spec: not(undefined) = undefined
            policy_rego=shape7_policy,
            input_json='{"role": "viewer"}',  # active field absent
        ),
        # Same bug with active=null (null is not bool true, so not(null==true) = not(false) = true in spec)
        # But null==true should be false (both args present), not undefined
        # → spec and OPA should agree here
        Tuple(
            shape_name="not-active-and-role-viewer",
            input_name="EXTENDED:active-null",
            spec_result="true",         # not(null == true) = not(false) = true
            policy_rego=shape7_policy,
            input_json='{"role": "viewer", "active": null}',
        ),
        # Bug 2: in_arr over object - spec returns undefined, OPA returns true
        Tuple(
            shape_name="groups-contains-ops",
            input_name="EXTENDED:groups-as-object",
            spec_result="undefined",    # in_arr only handles arrays
            policy_rego=shape6_policy,
            input_json='{"groups": {"team1": "ops", "team2": "dev"}}',
        ),
        # Additional: in_arr over string - both should be undefined
        Tuple(
            shape_name="groups-contains-ops",
            input_name="EXTENDED:groups-as-string",
            spec_result="undefined",
            policy_rego=shape6_policy,
            input_json='{"groups": "ops"}',
        ),
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="OPA/Rego differential test runner")
    ap.add_argument("--opa",    default=DEFAULT_OPA,
                    help="Path to OPA binary (default: /tmp/opa)")
    ap.add_argument("--output", default=None,
                    help="Write disagreements JSON to this file")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    opa_path = args.opa
    if not os.path.isfile(opa_path):
        print(f"[ERROR] OPA binary not found at {opa_path}", file=sys.stderr)
        print("Download: curl -fsSL https://github.com/open-policy-agent/opa/releases/download/v1.15.2/opa_linux_amd64_static -o /tmp/opa && chmod +x /tmp/opa",
              file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] Running Lean spec driver (lake exec measure-rego)...")
    tuples = run_lean_driver()
    extended = make_extended_tuples()
    print(f"[INFO] Got {len(tuples)} (shape, input) tuples from Lean spec")
    print(f"[INFO] Adding {len(extended)} extended bug-probe tuples")
    tuples = tuples + extended

    # Check OPA version
    ver_proc = subprocess.run([opa_path, "version"], capture_output=True, text=True)
    opa_version = ver_proc.stdout.split("\n")[0].strip() if ver_proc.returncode == 0 else "unknown"
    print(f"[INFO] OPA version: {opa_version}")
    print()

    results: list[Result] = []
    agreed = 0
    disagreed = 0
    bugs: list[dict] = []

    for t in tuples:
        opa_result = run_opa(opa_path, t.policy_rego, t.input_json)
        a = (t.spec_result == opa_result) or (
            # OPA returns {} (undefined) for a deny, which maps to "undefined" in our runner.
            # Rego spec: a rule that evaluates to false is semantically "deny" but
            # represented as undefined (no successful rule firing). So spec=false
            # and opa_result=undefined is *expected* for complete rules.
            t.spec_result == "false" and opa_result == "undefined"
        )
        r = Result(t=t, opa_result=opa_result, agreed=a)
        results.append(r)

        if a:
            agreed += 1
            if args.verbose:
                print(f"AGREE    {t.shape_name:40s} {t.input_name:25s} {t.spec_result}")
        else:
            disagreed += 1
            label = classify_disagreement(t, opa_result)
            print(f"DISAGREE {t.shape_name:40s} {t.input_name:25s} "
                  f"spec={t.spec_result} opa={opa_result}  [{label}]")

            bug_entry = {
                "shape": t.shape_name,
                "input": t.input_name,
                "spec_result": t.spec_result,
                "opa_result": opa_result,
                "classification": label,
                "policy_rego": t.policy_rego,
                "input_json": t.input_json,
            }
            bugs.append(bug_entry)

    print()
    print(f"=== Summary ===")
    print(f"Total tuples:    {len(tuples)}")
    print(f"Agreed:          {agreed}")
    print(f"Disagreed:       {disagreed}")
    agreement_rate = (agreed / len(tuples) * 100) if tuples else 0
    print(f"Agreement rate:  {agreement_rate:.1f}%")
    print(f"OPA version:     {opa_version}")

    if bugs:
        print()
        print(f"=== Disagreements ({len(bugs)}) ===")
        for b in bugs:
            print(f"  [{b['classification']}]")
            print(f"    shape: {b['shape']}")
            print(f"    input: {b['input']}")
            print(f"    spec:  {b['spec_result']}")
            print(f"    opa:   {b['opa_result']}")
            print(f"    policy: {b['policy_rego'].strip()}")
            print(f"    input_json: {b['input_json'][:120]}")
            print()

    if args.output:
        with open(args.output, "w") as f:
            json.dump({
                "opa_version": opa_version,
                "total": len(tuples),
                "agreed": agreed,
                "disagreed": disagreed,
                "bugs": bugs,
            }, f, indent=2)
        print(f"[INFO] Disagreements written to {args.output}")

    # Exit non-zero if bugs found (for CI)
    sys.exit(1 if any(
        "BUG" in b["classification"] for b in bugs
    ) else 0)


if __name__ == "__main__":
    main()
