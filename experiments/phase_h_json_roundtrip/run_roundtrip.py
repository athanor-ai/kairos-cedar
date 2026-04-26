#!/usr/bin/env python3
"""
run_roundtrip.py; orchestrates JSON↔Cedar round-trip probing on both impls.

Runs:
  1. cedar-go:    JSON → Policy.UnmarshalJSON → MarshalCedar → UnmarshalCedar → MarshalJSON → compare
  2. cedar-policy (Rust): cedar translate-policy --direction json-to-cedar |
                          cedar translate-policy --direction cedar-to-json → compare

Outputs per-probe results to stdout and per-finding markdown to disagreements/.

Usage (inside container):
  python3 run_roundtrip.py [--dry-run] [--go-only] [--rust-only]
"""

import json
import os
import subprocess
import sys
import tempfile
import argparse
from pathlib import Path
from collections import defaultdict

# ── Paths ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
HARNESS_DIR = SCRIPT_DIR / "go_harness"
DISAGREEMENTS_DIR = SCRIPT_DIR / "disagreements"
WORK_DIR = Path("/work")  # container mount point
CEDAR_GO_DIR = WORK_DIR / "cedar-go"

# ── Go harness build + run ────────────────────────────────────────────────────

def build_go_harness():
    """Build the Go round-trip harness inside the container (called within Docker)."""
    result = subprocess.run(
        ["go", "build", "-o", "/tmp/roundtrip_harness", "."],
        cwd=str(HARNESS_DIR),
        capture_output=True,
        text=True,
        env={**os.environ, "GOPATH": "/root/go"},
    )
    if result.returncode != 0:
        print("Go build failed:", result.stderr, file=sys.stderr)
        sys.exit(1)
    print("[go] harness built → /tmp/roundtrip_harness", file=sys.stderr)

def run_go_harness(probes: list[dict]) -> list[dict]:
    """Run all probes through the Go round-trip harness."""
    # Prepare NDJSON input
    ndjson = "\n".join(
        json.dumps({"id": p["id"], "policy_json": p["policy_json"]})
        for p in probes
    )

    result = subprocess.run(
        ["/tmp/roundtrip_harness"],
        input=ndjson,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        print("[go] harness exited non-zero:", result.returncode, file=sys.stderr)
        print(result.stderr[:500], file=sys.stderr)

    results = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            results.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"[go] bad output line: {line!r}: {e}", file=sys.stderr)

    return results


# ── Rust cedar-policy CLI round-trip ─────────────────────────────────────────

def run_rust_roundtrip(probe: dict) -> dict:
    """
    Run a single probe through cedar translate-policy round-trip.

    JSON → cedar text → JSON
    Returns dict with outcome/detail/cedar_text/out_json fields.
    """
    policy_json = json.dumps(probe["policy_json"])

    # Step 1: json-to-cedar
    try:
        r1 = subprocess.run(
            ["cedar", "translate-policy", "--direction", "json-to-cedar"],
            input=policy_json,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return {"outcome": "panic", "stage": "json_to_cedar", "detail": "timeout"}

    if r1.returncode != 0:
        return {
            "outcome": "parse_fail",
            "stage": "json_to_cedar",
            "detail": r1.stderr.strip() or r1.stdout.strip(),
        }

    cedar_text = r1.stdout.strip()

    # Step 2: cedar-to-json
    try:
        r2 = subprocess.run(
            ["cedar", "translate-policy", "--direction", "cedar-to-json"],
            input=cedar_text,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return {"outcome": "panic", "stage": "cedar_to_json", "detail": "timeout", "cedar_text": cedar_text}

    if r2.returncode != 0:
        return {
            "outcome": "parse_fail",
            "stage": "cedar_to_json",
            "detail": r2.stderr.strip() or r2.stdout.strip(),
            "cedar_text": cedar_text,
        }

    out_json_str = r2.stdout.strip()
    # The CLI outputs a policy set JSON; extract first policy
    try:
        out_parsed = json.loads(out_json_str)
        if isinstance(out_parsed, list) and len(out_parsed) > 0:
            out_json_single = out_parsed[0]
        elif isinstance(out_parsed, dict) and "staticPolicies" in out_parsed:
            # PolicySet format
            policies = out_parsed.get("staticPolicies", {})
            if isinstance(policies, dict) and policies:
                out_json_single = next(iter(policies.values()))
            elif isinstance(policies, list) and policies:
                out_json_single = policies[0]
            else:
                out_json_single = out_parsed
        else:
            out_json_single = out_parsed
    except json.JSONDecodeError:
        return {
            "outcome": "parse_fail",
            "stage": "compare",
            "detail": f"could not parse CLI output JSON: {out_json_str[:200]}",
            "cedar_text": cedar_text,
        }

    # Compare: normalize input vs output
    try:
        # Normalize input JSON for comparison
        input_norm = _normalize_policy_for_compare(probe["policy_json"])
        output_norm = _normalize_policy_for_compare(out_json_single)
    except Exception as e:
        return {
            "outcome": "parse_fail",
            "stage": "compare",
            "detail": f"normalize error: {e}",
            "cedar_text": cedar_text,
            "out_json": out_json_str,
        }

    if input_norm == output_norm:
        return {
            "outcome": "clean",
            "stage": "compare",
            "detail": "round-trip identity holds",
            "cedar_text": cedar_text,
            "out_json": out_json_str,
        }
    else:
        return {
            "outcome": "silent_diff",
            "stage": "compare",
            "detail": f"INPUT:  {json.dumps(input_norm)}\nOUTPUT: {json.dumps(output_norm)}",
            "cedar_text": cedar_text,
            "out_json": out_json_str,
        }


def _normalize_policy_for_compare(policy: dict) -> dict:
    """
    Return a normalized dict for semantic comparison.
    Removes non-semantic fields (positions, etc.) and sorts where order doesn't matter.
    """
    if not isinstance(policy, dict):
        return policy
    # Remove non-semantic keys that may differ
    skip = {"position", "filename"}
    out = {}
    for k, v in sorted(policy.items()):
        if k in skip:
            continue
        if isinstance(v, dict):
            out[k] = _normalize_policy_for_compare(v)
        elif isinstance(v, list):
            out[k] = [_normalize_policy_for_compare(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    return out


# ── Reporting ─────────────────────────────────────────────────────────────────

def categorize_probe(probe: dict) -> str:
    """Return the probe's declared category."""
    return probe.get("category", "unknown")


def write_finding(probe: dict, go_result: dict, rust_result: dict | None, finding_id: str):
    """Write a per-finding markdown to disagreements/."""
    DISAGREEMENTS_DIR.mkdir(exist_ok=True)
    slug = probe["id"].lower().replace("-", "_").replace(" ", "_")
    out_path = DISAGREEMENTS_DIR / f"{finding_id}_{slug}.md"

    go_outcome = go_result.get("outcome", "?")
    rust_outcome = (rust_result or {}).get("outcome", "not_run")

    content = f"""# Finding {finding_id}: {probe['id']}

**Category:** {probe.get('category', 'unknown')}
**Note:** {probe.get('note', '')}

## Probe Input

```json
{json.dumps(probe['policy_json'], indent=2)}
```

## cedar-go result

- **Outcome:** `{go_outcome}`
- **Stage:** `{go_result.get('stage', '?')}`
- **Detail:**
```
{go_result.get('detail', '')}
```
- **Cedar text produced:** `{go_result.get('cedar_text', '')}`
- **Output JSON:** `{go_result.get('out_json', '')}`

## cedar-policy (Rust) result

- **Outcome:** `{rust_outcome}`
- **Stage:** `{(rust_result or {}).get('stage', '?')}`
- **Detail:**
```
{(rust_result or {}).get('detail', '')}
```
- **Cedar text produced:** `{(rust_result or {}).get('cedar_text', '')}`

## Classification

{"- cedar-go **PANICS** where Rust returns parse_fail" if go_outcome == "panic" and rust_outcome == "parse_fail" else ""}
{"- cedar-go **PANICS**; input accepted then crash" if go_outcome == "panic" else ""}
{"- cedar-go **silent-drops** information (round-trip not identity)" if go_outcome == "silent_diff" else ""}
{"- cedar-go and cedar-policy DISAGREE on parse validity" if go_outcome != rust_outcome and go_outcome in ("parse_fail", "clean") and rust_outcome in ("parse_fail", "clean") else ""}
{"- Both impls clean round-trip" if go_outcome == "clean" and rust_outcome == "clean" else ""}
"""
    out_path.write_text(content)
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Generate probes only, no execution")
    parser.add_argument("--go-only", action="store_true", help="Only run cedar-go harness")
    parser.add_argument("--rust-only", action="store_true", help="Only run cedar-policy CLI")
    parser.add_argument("--probe-file", default=None, help="Custom probe NDJSON file (default: generate from probe_inputs.py)")
    args = parser.parse_args()

    # ── Load probes ──────────────────────────────────────────────────────────
    if args.probe_file:
        probes = []
        with open(args.probe_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    probes.append(json.loads(line))
    else:
        # Import probe_inputs module
        import importlib.util
        spec = importlib.util.spec_from_file_location("probe_inputs", SCRIPT_DIR / "probe_inputs.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        probes = mod.PROBES

    print(f"[run] {len(probes)} probes loaded", file=sys.stderr)
    print(f"[run] categories: { {p.get('category','?') for p in probes} }", file=sys.stderr)

    if args.dry_run:
        for p in probes:
            print(p["id"], p.get("category"))
        return

    # ── Build & run Go harness ───────────────────────────────────────────────
    go_results_map = {}
    if not args.rust_only:
        build_go_harness()
        go_raw = run_go_harness(probes)
        for r in go_raw:
            go_results_map[r["id"]] = r
        print(f"[go] {len(go_raw)} results", file=sys.stderr)

    # ── Run Rust harness ─────────────────────────────────────────────────────
    rust_results_map = {}
    if not args.go_only:
        print(f"[rust] running {len(probes)} probes...", file=sys.stderr)
        for p in probes:
            r = run_rust_roundtrip(p)
            r["id"] = p["id"]
            rust_results_map[p["id"]] = r
        print(f"[rust] {len(rust_results_map)} results", file=sys.stderr)

    # ── Collate + classify ───────────────────────────────────────────────────
    all_results = []
    finding_count = 0
    stats = defaultdict(lambda: defaultdict(int))  # category → outcome → count

    for p in probes:
        pid = p["id"]
        category = p.get("category", "unknown")
        go_r = go_results_map.get(pid, {"outcome": "not_run"})
        rust_r = rust_results_map.get(pid, None)

        go_outcome = go_r.get("outcome", "?")
        rust_outcome = (rust_r or {}).get("outcome", "not_run")

        stats[category][f"go:{go_outcome}"] += 1
        if rust_r:
            stats[category][f"rust:{rust_outcome}"] += 1

        row = {
            "id": pid,
            "category": category,
            "go_outcome": go_outcome,
            "go_stage": go_r.get("stage", ""),
            "rust_outcome": rust_outcome,
            "rust_stage": (rust_r or {}).get("stage", ""),
            "is_finding": False,
        }

        # Findings: panics and silent diffs (go), plus cross-impl disagreements
        is_go_finding = go_outcome in ("panic", "silent_diff")
        is_cross_finding = (
            rust_r is not None and
            go_outcome != "not_run" and
            rust_outcome != "not_run" and
            go_outcome != rust_outcome and
            # Only flag if at least one side thinks it's valid
            (go_outcome in ("clean", "silent_diff") or rust_outcome in ("clean", "silent_diff"))
        )

        if is_go_finding or is_cross_finding:
            finding_count += 1
            row["is_finding"] = True
            fid = f"F{finding_count:03d}"
            row["finding_id"] = fid
            path = write_finding(p, go_r, rust_r, fid)
            print(f"[finding] {fid} {pid}: go={go_outcome} rust={rust_outcome} → {path}", file=sys.stderr)

        all_results.append(row)
        print(json.dumps(row))

    # ── Print summary ────────────────────────────────────────────────────────
    print("\n" + "="*70, file=sys.stderr)
    print("SUMMARY", file=sys.stderr)
    print("="*70, file=sys.stderr)
    for cat in sorted(stats.keys()):
        print(f"\n  [{cat}]", file=sys.stderr)
        for k, v in sorted(stats[cat].items()):
            print(f"    {k}: {v}", file=sys.stderr)
    print(f"\n  Total findings: {finding_count}", file=sys.stderr)
    print(f"  Findings written to: {DISAGREEMENTS_DIR}", file=sys.stderr)

    # Return non-zero if any panics found
    panics = sum(1 for r in all_results if r["go_outcome"] == "panic")
    if panics > 0:
        print(f"\n  !! {panics} PANICS detected in cedar-go !!", file=sys.stderr)


if __name__ == "__main__":
    main()
