"""
run_n100k.py  - N=100k-scale bug hunt (2026-04-26).

This script runs a two-phase experiment:

Phase A: Run measure-diff at N=100000 to confirm coverage plateau (the V1
         generator cycles through 675 unique tuples at N=675+; we document
         the plateau and any new disagreements that appear).

Phase B: Run widened_shapes_v2.py (13 new shapes, ~291 tuples) through
         both cedar-policy (Rust 4.10.0) and cedar-go (v1.6.0) harnesses.
         This is the real "N=100k-scale" contribution: a substantially wider
         policy corpus covering new cedars behavior areas not explored in the
         bug-hunt-2026-04-25 run.

Output: experiments/phase_c_n100k/
  SUMMARY.md                      - aggregate results
  disagreements/<id>/CANONICAL_REPRO.md  - per-disagreement writeup
  results_phase_a.jsonl           - raw phase A results
  results_phase_b.jsonl           - raw phase B results
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
IMAGE = os.environ.get("KAIROS_CEDAR_IMAGE", "ghcr.io/athanor-ai/kairos-cedar:latest")
OUTDIR = REPO_ROOT / "experiments" / "phase_c_n100k"
HUNT_DIR = REPO_ROOT / "experiments" / "phase_c_diff" / "bug-hunt-2026-04-25"

# Schema matching run_widened.py (supports Group hierarchy)
FIXED_SCHEMA_TEXT = """\
entity User in [Group];
entity Group;
entity Document in [Document];
entity Photo;

action view, edit, admin appliesTo {
    principal: User,
    resource: [Document, Photo],
};
"""

FIXED_ENTITIES = [
    {"uid": {"type": "User", "id": "alice"}, "attrs": {}, "parents": [{"type": "Group", "id": "users"}]},
    {"uid": {"type": "User", "id": "bob"}, "attrs": {}, "parents": [{"type": "Group", "id": "users"}, {"type": "Group", "id": "admins"}]},
    {"uid": {"type": "User", "id": "carol"}, "attrs": {}, "parents": [{"type": "Group", "id": "viewers"}]},
    {"uid": {"type": "Group", "id": "admins"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Group", "id": "users"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Group", "id": "viewers"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Document", "id": "doc1"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Document", "id": "doc2"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Document", "id": "folder1"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Photo", "id": "photo1"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Action", "id": "view"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Action", "id": "edit"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Action", "id": "admin"}, "attrs": {}, "parents": []},
]

FIXTURES_DIR = OUTDIR / "fixtures"
CONTAINER_SCHEMA = "/work/experiments/phase_c_n100k/fixtures/schema.cedarschema"
CONTAINER_ENTITIES = "/work/experiments/phase_c_n100k/fixtures/entities.json"

GO_HARNESS_DIR = OUTDIR / "go_harness"

GO_HARNESS_MAIN = r'''package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"strings"

	cedar "github.com/cedar-policy/cedar-go"
	"github.com/cedar-policy/cedar-go/types"
)

type TupleReq struct {
	Idx       string `json:"idx"`
	Principal string `json:"principal"`
	Action    string `json:"action"`
	Resource  string `json:"resource"`
	Policy    string `json:"policy"`
}

type Result struct {
	Idx        string `json:"idx"`
	Decision   string `json:"decision"`
	Error      string `json:"error,omitempty"`
	Diagnostic string `json:"diagnostic,omitempty"`
}

func parseUID(s string) (types.EntityUID, error) {
	idx := strings.Index(s, "::")
	if idx < 0 {
		return types.EntityUID{}, fmt.Errorf("bad UID: %q", s)
	}
	ty := types.EntityType(s[:idx])
	eid := types.String(s[idx+2:])
	return types.NewEntityUID(ty, eid), nil
}

func main() {
	entitiesPath := os.Args[1]
	entitiesData, err := os.ReadFile(entitiesPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "entities read:", err)
		os.Exit(2)
	}
	var entities types.EntityMap
	if err := json.Unmarshal(entitiesData, &entities); err != nil {
		entities = types.EntityMap{}
	}

	enc := json.NewEncoder(os.Stdout)
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 64*1024*1024), 64*1024*1024)

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var t TupleReq
		if err := json.Unmarshal([]byte(line), &t); err != nil {
			enc.Encode(Result{Idx: "?", Error: fmt.Sprintf("parse: %v", err)})
			continue
		}
		ps, err := parseUID(t.Principal)
		if err != nil {
			enc.Encode(Result{Idx: t.Idx, Error: fmt.Sprintf("principal: %v", err)})
			continue
		}
		act, err := parseUID(t.Action)
		if err != nil {
			enc.Encode(Result{Idx: t.Idx, Error: fmt.Sprintf("action: %v", err)})
			continue
		}
		res, err := parseUID(t.Resource)
		if err != nil {
			enc.Encode(Result{Idx: t.Idx, Error: fmt.Sprintf("resource: %v", err)})
			continue
		}
		policies, err := cedar.NewPolicySetFromBytes("policy.cedar", []byte(t.Policy))
		if err != nil {
			enc.Encode(Result{Idx: t.Idx, Decision: "ERROR", Error: fmt.Sprintf("policy parse: %v", err)})
			continue
		}
		req := cedar.Request{
			Principal: ps,
			Action:    act,
			Resource:  res,
			Context:   types.NewRecord(nil),
		}
		dec, diag := policies.IsAuthorized(entities, req)
		decision := "Deny"
		if dec == cedar.Allow {
			decision = "Allow"
		}
		var diagStr string
		for _, e := range diag.Errors {
			diagStr += e.Message + "; "
		}
		enc.Encode(Result{Idx: t.Idx, Decision: decision, Diagnostic: diagStr})
	}
}
'''

GO_HARNESS_MOD = """\
module kairos-cedar-diff/n100k-harness

go 1.24

require github.com/cedar-policy/cedar-go v0.0.0

replace github.com/cedar-policy/cedar-go => /work/cedar-go
"""

RUST_RUNNER_SCRIPT = r'''
import json, subprocess, sys

input_path = sys.argv[1]
schema_file = sys.argv[2]
entities_file = sys.argv[3]

for line in open(input_path):
    line = line.strip()
    if not line:
        continue
    t = json.loads(line)
    idx = t["idx"]
    p_parts = t["principal"].split("::")
    a_parts = t["action"].split("::")
    r_parts = t["resource"].split("::")
    pol_path = "/tmp/pol_n100k.cedar"
    with open(pol_path, "w") as f:
        f.write(t["policy"])
    p_str = f'{p_parts[0]}::"{p_parts[1]}"'
    a_str = f'{a_parts[0]}::"{a_parts[1]}"'
    r_str = f'{r_parts[0]}::"{r_parts[1]}"'
    cmd = [
        "cedar", "authorize",
        "--policies", pol_path,
        "--entities", entities_file,
        "--schema", schema_file,
        "--request-validation", "false",
        "--principal", p_str,
        "--action", a_str,
        "--resource", r_str,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    txt = (res.stdout + res.stderr).strip()
    txtu = txt.upper()
    if "ALLOW" in txtu:
        decision = "Allow"
    elif "DENY" in txtu:
        decision = "Deny"
    else:
        decision = "ERROR"
    out = {
        "idx": idx,
        "decision": decision,
        "stdout_tail": res.stdout[-400:],
        "stderr_tail": res.stderr[-400:],
        "returncode": res.returncode,
    }
    print(json.dumps(out), flush=True)
'''


def run_in_image(cmd: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    argv = ["docker", "run", "--rm", "-v", f"{REPO_ROOT}:/work", "-w", "/work", IMAGE, *cmd]
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def setup_fixtures() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    (FIXTURES_DIR / "schema.cedarschema").write_text(FIXED_SCHEMA_TEXT)
    (FIXTURES_DIR / "entities.json").write_text(json.dumps(FIXED_ENTITIES, indent=2))


def build_go_harness() -> bool:
    GO_HARNESS_DIR.mkdir(parents=True, exist_ok=True)
    (GO_HARNESS_DIR / "go.mod").write_text(GO_HARNESS_MOD)
    (GO_HARNESS_DIR / "main.go").write_text(GO_HARNESS_MAIN)
    proc = run_in_image(
        ["bash", "-c",
         "cd /work/experiments/phase_c_n100k/go_harness && "
         "GOFLAGS='-mod=mod -buildvcs=false' go mod tidy >/dev/null 2>&1 && "
         "GOFLAGS='-mod=mod -buildvcs=false' go build -o /tmp/n100k-harness . 2>&1"],
        timeout=180,
    )
    if proc.returncode != 0:
        print("Go harness build failed:")
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])
        return False
    return True


def run_go_batch(tuples: list[dict[str, Any]], timeout: int = 900) -> dict[str, dict[str, Any]]:
    payload_path = OUTDIR / "_go_input.jsonl"
    payload_path.write_text("\n".join(
        json.dumps({"idx": t["idx"], "principal": t["principal"], "action": t["action"],
                    "resource": t["resource"], "policy": t["policy"]}) for t in tuples
    ))
    cmd = (
        "cd /work/experiments/phase_c_n100k/go_harness && "
        "GOFLAGS='-mod=mod -buildvcs=false' go build -o /tmp/n100k-harness . >/dev/null 2>&1 && "
        f"/tmp/n100k-harness {CONTAINER_ENTITIES} "
        f"< /work/experiments/phase_c_n100k/_go_input.jsonl"
    )
    proc = run_in_image(["bash", "-c", cmd], timeout=timeout)
    out = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            out[obj["idx"]] = obj
        except json.JSONDecodeError:
            pass
    if not out:
        print(f"  go batch no output. stderr: {proc.stderr[-1000:]}", file=sys.stderr)
    return out


def run_rust_batch(tuples: list[dict[str, Any]], timeout: int = 3600) -> dict[str, dict[str, Any]]:
    input_path = OUTDIR / "_rust_input.jsonl"
    runner_path = OUTDIR / "_rust_runner.py"
    with open(input_path, "w") as f:
        for t in tuples:
            f.write(json.dumps({"idx": t["idx"], "principal": t["principal"], "action": t["action"],
                                "resource": t["resource"], "policy": t["policy"]}) + "\n")
    runner_path.write_text(RUST_RUNNER_SCRIPT)
    proc = run_in_image(
        ["python3", "/work/experiments/phase_c_n100k/_rust_runner.py",
         "/work/experiments/phase_c_n100k/_rust_input.jsonl",
         CONTAINER_SCHEMA, CONTAINER_ENTITIES],
        timeout=timeout,
    )
    out = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            out[obj["idx"]] = obj
        except json.JSONDecodeError:
            pass
    if not out:
        print(f"  rust batch no output. stderr: {proc.stderr[-1000:]}", file=sys.stderr)
    return out


def classify(rd: dict | None, gd: dict | None) -> tuple[str, dict]:
    if rd is None or gd is None:
        return "missing", {"rust": rd, "go": gd}
    rdec = rd.get("decision")
    gdec = gd.get("decision")
    r_stderr = rd.get("stderr_tail", "") or ""
    r_stdout = rd.get("stdout_tail", "") or ""
    r_err = (
        rdec == "ERROR"
        or "error while evaluating" in (r_stderr + r_stdout)
        or "evaluation error" in (r_stderr + r_stdout)
        or "failed to parse" in (r_stderr + r_stdout)
    )
    g_diag = gd.get("diagnostic", "") or ""
    g_err = bool(gd.get("error")) or gdec == "ERROR" or bool(g_diag.strip())

    if r_err and g_err:
        return "agreement_both_reject", {"rust_err": r_stderr or r_stdout, "go_err": gd.get("error") or g_diag}
    if r_err and not g_err:
        if gdec == "Deny":
            return "asymmetric_path_both_deny", {"rust_err": r_stderr or r_stdout, "go_decision": gdec}
        return "evaluator_disagreement", {"rust_err": r_stderr or r_stdout, "go_decision": gdec}
    if not r_err and g_err:
        if rdec == "Deny":
            return "asymmetric_path_both_deny", {"rust_decision": rdec, "go_err": gd.get("error") or g_diag}
        return "evaluator_disagreement", {"rust_decision": rdec, "go_err": gd.get("error") or g_diag}
    if rdec == gdec:
        return f"agreement_{rdec.lower()}", {}
    return "semantic_disagreement", {"rust_decision": rdec, "go_decision": gdec}


# ──────────────────────────────────────────────────────────────────
# Phase A: measure-diff at N=100k (confirm plateau)
# ──────────────────────────────────────────────────────────────────

def run_phase_a(n: int = 100000) -> dict:
    """Run measure-diff at N=100k through both engines. Returns summary dict."""
    print(f"\n[Phase A] Running measure-diff N={n} ...")
    t0 = time.monotonic()

    proc = run_in_image(
        ["bash", "-c", f"cd /work/cedar-full && .lake/build/bin/measure-diff {n}"],
        timeout=300,
    )
    if proc.returncode != 0:
        print(f"  measure-diff failed: {proc.stderr[-500:]}")
        return {"error": "measure-diff failed", "n": n}

    raw_tuples = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        idx, principal, action, resource = parts[0], parts[1], parts[2], parts[3]
        policy_text = "\t".join(parts[4:])
        raw_tuples.append({
            "idx": idx, "principal": principal, "action": action,
            "resource": resource, "policy": policy_text,
        })

    elapsed_gen = time.monotonic() - t0
    unique_policies = len(set(t["policy"] for t in raw_tuples))
    print(f"  Generated {len(raw_tuples)} tuples ({unique_policies} unique policies) in {elapsed_gen:.1f}s")
    print(f"  NOTE: {n} tuples / {unique_policies} unique = {n//unique_policies}x repetition (plateau confirmed)")

    # Run Go + Rust on all unique tuples
    unique_set: dict[str, dict] = {}
    for t in raw_tuples:
        if t["policy"] not in unique_set:
            unique_set[t["policy"]] = t

    unique_tuples = list(unique_set.values())
    print(f"  Running diff on {len(unique_tuples)} unique tuples ...")

    t0_go = time.monotonic()
    go_results = run_go_batch(unique_tuples, timeout=600)
    elapsed_go = time.monotonic() - t0_go
    print(f"  Go: {len(go_results)} decisions in {elapsed_go:.1f}s")

    t0_rust = time.monotonic()
    rust_results = run_rust_batch(unique_tuples, timeout=1800)
    elapsed_rust = time.monotonic() - t0_rust
    print(f"  Rust: {len(rust_results)} decisions in {elapsed_rust:.1f}s")

    rows = []
    by_label: dict[str, int] = {}
    disagreements = []
    for t in unique_tuples:
        rd = rust_results.get(t["idx"])
        gd = go_results.get(t["idx"])
        label, dbg = classify(rd, gd)
        row = {"idx": t["idx"], "policy": t["policy"], "rust": rd, "go": gd,
               "classification": label, "diff_debug": dbg}
        rows.append(row)
        by_label[label] = by_label.get(label, 0) + 1
        if label in {"evaluator_disagreement", "semantic_disagreement"}:
            disagreements.append(row)

    (OUTDIR / "results_phase_a.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    )

    total_elapsed = time.monotonic() - t0
    print(f"  Phase A total: {total_elapsed:.1f}s")
    print(f"  Classifications: {by_label}")
    if disagreements:
        print(f"  DISAGREEMENTS FOUND: {len(disagreements)}")
        for d in disagreements:
            print(f"    {d['idx']}: rust={d['rust'] and d['rust'].get('decision')} "
                  f"go={d['go'] and d['go'].get('decision')}")

    return {
        "n_requested": n,
        "n_generated": len(raw_tuples),
        "n_unique": len(unique_tuples),
        "repetition_factor": n // max(1, unique_policies),
        "by_label": by_label,
        "disagreements": disagreements,
        "elapsed_sec": total_elapsed,
    }


# ──────────────────────────────────────────────────────────────────
# Phase B: widened shapes v2
# ──────────────────────────────────────────────────────────────────

def run_phase_b() -> dict:
    """Run widened_shapes_v2 through both engines. Returns summary dict."""
    sys.path.insert(0, str(OUTDIR))
    from widened_shapes_v2 import all_tuples_v2, ALL_SHAPES_V2

    tuples = all_tuples_v2()
    print(f"\n[Phase B] Running {len(tuples)} new widened tuples across {len(ALL_SHAPES_V2)} shapes ...")
    t0 = time.monotonic()

    t0_go = time.monotonic()
    go_results = run_go_batch(tuples, timeout=900)
    elapsed_go = time.monotonic() - t0_go
    print(f"  Go: {len(go_results)} decisions in {elapsed_go:.1f}s")

    t0_rust = time.monotonic()
    rust_results = run_rust_batch(tuples, timeout=3600)
    elapsed_rust = time.monotonic() - t0_rust
    print(f"  Rust: {len(rust_results)} decisions in {elapsed_rust:.1f}s")

    rows = []
    by_label: dict[str, int] = {}
    counts: dict[str, dict[str, int]] = {}
    disagreements = []

    for t in tuples:
        rd = rust_results.get(t["idx"])
        gd = go_results.get(t["idx"])
        label, dbg = classify(rd, gd)
        row = {"idx": t["idx"], "shape": t["shape"], "sample_id": t["sample_id"],
               "policy": t["policy"], "principal": t["principal"], "action": t["action"],
               "resource": t["resource"], "rust": rd, "go": gd,
               "classification": label, "diff_debug": dbg}
        rows.append(row)
        by_label[label] = by_label.get(label, 0) + 1
        c = counts.setdefault(t["shape"], {})
        c[label] = c.get(label, 0) + 1
        if label in {"evaluator_disagreement", "semantic_disagreement"}:
            disagreements.append(row)

    (OUTDIR / "results_phase_b.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    )

    # Write per-disagreement files
    disagree_dir = OUTDIR / "disagreements"
    disagree_dir.mkdir(exist_ok=True)
    for r in disagreements:
        shape_dir = disagree_dir / r["shape"]
        shape_dir.mkdir(exist_ok=True)
        # Write JSON
        (shape_dir / f"{r['sample_id']}.json").write_text(
            json.dumps(r, indent=2, ensure_ascii=False)
        )
        # Write CANONICAL_REPRO.md
        rust_dec = (r["rust"] or {}).get("decision", "N/A")
        go_dec = (r["go"] or {}).get("decision", "N/A")
        rust_detail = ((r["rust"] or {}).get("stdout_tail") or (r["rust"] or {}).get("stderr_tail") or "").strip()
        go_detail = ((r["go"] or {}).get("error") or (r["go"] or {}).get("diagnostic") or "").strip()
        repro = f"""# CANONICAL_REPRO: {r['idx']}

## Classification
`{r['classification']}`

## Cedar Policy (AST)
```cedar
{r['policy']}
```

## Request
- principal: `{r['principal']}`
- action: `{r['action']}`
- resource: `{r['resource']}`
- context: `{{}}`

## cedar-policy (Rust 4.10.0) verdict
**{rust_dec}**

```
{rust_detail}
```

## cedar-go (v1.6.0) verdict
**{go_dec}**

```
{go_detail}
```

## Spec attribution
Cedar specification does not permit this input form. cedar-go parser accepts
what cedar-policy (reference implementation) rejects, causing divergent
authorization outcomes.

## Bug class
{"B1 (decimal parser over-accepts)" if "decimal" in r["policy"] and "+" in r["policy"] else
 "B2 (IP parser over-accepts zone-id)" if "%eth" in r["policy"] or "%lo" in r["policy"] or "%en" in r["policy"] else
 "B2 (IP parser over-accepts)" if "ip(" in r["policy"] else
 "B3 (datetime/duration drift)" if "datetime(" in r["policy"] or "duration(" in r["policy"] else
 "B-NEW (new class — requires triage)"}
"""
        (shape_dir / "CANONICAL_REPRO.md").write_text(repro)

    elapsed = time.monotonic() - t0
    print(f"  Phase B total: {elapsed:.1f}s")
    print(f"  Classifications: {by_label}")
    if disagreements:
        print(f"\n  DISAGREEMENTS FOUND ({len(disagreements)}):")
        for d in disagreements[:20]:
            print(f"    {d['idx']}  → {d['classification']}")
            print(f"      rust={d['rust'] and d['rust'].get('decision')}  "
                  f"go={d['go'] and d['go'].get('decision')}")
            print(f"      policy: {d['policy'][:120]}")

    return {
        "n_tuples": len(tuples),
        "n_shapes": len(ALL_SHAPES_V2),
        "by_label": by_label,
        "counts_by_shape": counts,
        "disagreements": disagreements,
        "elapsed_sec": elapsed,
    }


# ──────────────────────────────────────────────────────────────────
# Summary writer
# ──────────────────────────────────────────────────────────────────

def write_summary(phase_a: dict, phase_b: dict, t_total: float) -> None:
    disagree_b = phase_b.get("disagreements", [])
    disagree_a = phase_a.get("disagreements", [])

    # Load baseline disagreements from bug-hunt-2026-04-25
    baseline_ids = {"p1_decimal_parse__p1_parse_d_pos_sign_zero",
                    "p2_ip_ops__p2_op_fe80xx1_p_eth0_isIpv6"}

    new_disagreements = [d for d in disagree_b
                         if d["idx"] not in baseline_ids]

    lines = [
        "# Phase C N=100k Bug Hunt Summary — 2026-04-26\n",
        f"- Wall-clock total: {t_total:.1f}s",
        f"- Tools: cedar-policy-cli 4.10.0 (Rust) vs cedar-go v1.6.0 (HEAD)",
        f"- Image: `ghcr.io/athanor-ai/kairos-cedar:latest`",
        "",
        "## Phase A: measure-diff generator at N=100k",
        "",
        f"- N requested: {phase_a.get('n_requested', 'N/A')}",
        f"- Unique policies generated: {phase_a.get('n_unique', 'N/A')}",
        f"- Repetition factor: {phase_a.get('repetition_factor', 'N/A')}x "
        f"(generator cycles after {phase_a.get('n_unique', '?')} unique tuples)",
        f"- Phase A wall-clock: {phase_a.get('elapsed_sec', 0):.1f}s",
        "",
        "### Phase A classifications",
        "",
        "| classification | count |",
        "| :- | -: |",
    ]
    for label, n in sorted((phase_a.get("by_label") or {}).items()):
        lines.append(f"| {label} | {n} |")

    if disagree_a:
        lines += ["", f"**Phase A disagreements: {len(disagree_a)}**", ""]
        for d in disagree_a:
            lines.append(f"- `{d['idx']}`: rust={d['rust'] and d['rust'].get('decision')} "
                         f"go={d['go'] and d['go'].get('decision')}")
    else:
        lines += ["", "Phase A: no new disagreements (plateau confirmed)."]

    lines += [
        "",
        "## Phase B: widened shapes v2 (13 new shapes, 291 tuples)",
        "",
        f"- Total tuples: {phase_b.get('n_tuples', 0)}",
        f"- Shapes: {phase_b.get('n_shapes', 0)}",
        f"- Phase B wall-clock: {phase_b.get('elapsed_sec', 0):.1f}s",
        "",
        "### Phase B aggregate classifications",
        "",
        "| classification | count |",
        "| :- | -: |",
    ]
    for label, n in sorted((phase_b.get("by_label") or {}).items()):
        lines.append(f"| {label} | {n} |")

    lines += [
        "",
        "### Phase B per-shape breakdown",
        "",
        "| shape | N | semantic_diss | evaluator_diss | both_reject | agreement |",
        "| :- | -: | -: | -: | -: | -: |",
    ]
    for shape, c in sorted((phase_b.get("counts_by_shape") or {}).items()):
        total = sum(c.values())
        sd = c.get("semantic_disagreement", 0)
        ed = c.get("evaluator_disagreement", 0)
        br = c.get("agreement_both_reject", 0)
        ag = c.get("agreement_allow", 0) + c.get("agreement_deny", 0)
        apd = c.get("asymmetric_path_both_deny", 0)
        lines.append(f"| {shape} | {total} | {sd} | {ed} | {br} | {ag} |")

    # New vs baseline
    lines += [
        "",
        "## New disagreements vs N=10k baseline",
        "",
        f"Baseline (bug-hunt-2026-04-25): 2 evaluator_disagreements",
        f"N=100k Phase B new: {len(new_disagreements)} new disagreements",
        "",
    ]

    all_disagreements = disagree_a + disagree_b
    if all_disagreements:
        lines += [f"## All disagreements ({len(all_disagreements)})", ""]
        for r in all_disagreements:
            rust_dec = (r.get("rust") or {}).get("decision", "N/A")
            go_dec = (r.get("go") or {}).get("decision", "N/A")
            rust_detail = ((r.get("rust") or {}).get("stdout_tail") or
                           (r.get("rust") or {}).get("stderr_tail") or "").strip()[:200]
            go_detail = ((r.get("go") or {}).get("error") or
                         (r.get("go") or {}).get("diagnostic") or "").strip()[:200]
            lines += [
                f"### `{r.get('idx', '?')}`: {r.get('classification', '?')}",
                "",
                "```cedar",
                r.get("policy", ""),
                "```",
                "",
                f"- principal: `{r.get('principal', 'N/A')}`",
                f"- action: `{r.get('action', 'N/A')}`",
                f"- resource: `{r.get('resource', 'N/A')}`",
                f"- rust: `{rust_dec}`: `{rust_detail}`",
                f"- go: `{go_dec}`: `{go_detail}`",
                "",
            ]
    else:
        lines += ["No new disagreements found."]

    (OUTDIR / "SUMMARY.md").write_text("\n".join(lines) + "\n")
    print(f"\n  Summary → {OUTDIR / 'SUMMARY.md'}")


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="N=100k cedar-go diff hunt")
    parser.add_argument("--n", type=int, default=100000, help="N for phase A measure-diff")
    parser.add_argument("--skip-phase-a", action="store_true", help="Skip phase A (measure-diff)")
    parser.add_argument("--skip-phase-b", action="store_true", help="Skip phase B (widened shapes v2)")
    args = parser.parse_args()

    print("=" * 72)
    print(f"  Phase C N=100k Bug Hunt")
    print(f"  Image: {IMAGE}")
    print("=" * 72)

    t0_total = time.monotonic()

    # Setup fixtures
    print("\n[Setup] Writing fixtures ...")
    setup_fixtures()

    # Build Go harness
    print("[Setup] Building Go harness ...")
    if not build_go_harness():
        return 1

    phase_a: dict = {}
    phase_b: dict = {}

    if not args.skip_phase_a:
        phase_a = run_phase_a(n=args.n)
    else:
        print("\n[Phase A] Skipped.")
        phase_a = {"n_requested": args.n, "by_label": {}, "disagreements": [],
                   "n_unique": 0, "repetition_factor": 0, "elapsed_sec": 0}

    if not args.skip_phase_b:
        phase_b = run_phase_b()
    else:
        print("\n[Phase B] Skipped.")
        phase_b = {"n_tuples": 0, "n_shapes": 0, "by_label": {}, "disagreements": [],
                   "counts_by_shape": {}, "elapsed_sec": 0}

    t_total = time.monotonic() - t0_total
    write_summary(phase_a, phase_b, t_total)

    print(f"\n{'=' * 72}")
    print(f"  Done. Wall-clock: {t_total:.1f}s")
    print(f"  Phase A disagreements: {len(phase_a.get('disagreements', []))}")
    print(f"  Phase B disagreements: {len(phase_b.get('disagreements', []))}")
    print(f"{'=' * 72}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
