"""
run_widened.py  - execute the widened shapes from widened_shapes.py against
both cedar-policy (Rust) and cedar-go and report disagreements.

Each tuple is dispatched independently. Per-tuple we record:
  - rust_decision      ∈ {Allow, Deny, ERROR(...), parse_error}
  - go_decision        ∈ {Allow, Deny, ERROR(...), parse_error}
  - rust_stderr_tail   for diagnosis
  - go_stderr_tail     for diagnosis
  - classification:
       agreement              - both Allow or both Deny
       agreement_both_reject  - both ERROR/parse_error
       generator_artifact     - both reject but for different reasons
                                   (we still call this an *agreement* on outcome)
       evaluator_disagreement - one Allow/Deny, other ERROR
       semantic_disagreement  - both succeed, but Allow vs Deny

Usage:
    python3 experiments/phase_c_diff/bug-hunt-2026-04-25/run_widened.py
        [--shape p1_decimal_parse]
        [--out bug-hunt-2026-04-25/results.jsonl]
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

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "experiments" / "phase_c_diff" / "bug-hunt-2026-04-25"))

from widened_shapes import all_tuples, ALL_SHAPES  # noqa: E402

IMAGE = os.environ.get("KAIROS_CEDAR_IMAGE", "ghcr.io/athanor-ai/kairos-cedar:latest")
HUNT_DIR = REPO_ROOT / "experiments" / "phase_c_diff" / "bug-hunt-2026-04-25"

# Reuse fixture set from V1 harness
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

FIXTURES_DIR = HUNT_DIR / "fixtures"
FIXTURES_DIR.mkdir(exist_ok=True)
(FIXTURES_DIR / "schema.cedarschema").write_text(FIXED_SCHEMA_TEXT)
(FIXTURES_DIR / "entities.json").write_text(json.dumps(FIXED_ENTITIES, indent=2))

CONTAINER_SCHEMA = "/work/experiments/phase_c_diff/bug-hunt-2026-04-25/fixtures/schema.cedarschema"
CONTAINER_ENTITIES = "/work/experiments/phase_c_diff/bug-hunt-2026-04-25/fixtures/entities.json"


def run_in_image(cmd: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    argv = [
        "docker", "run", "--rm",
        "-v", f"{REPO_ROOT}:/work",
        "-w", "/work",
        IMAGE,
        *cmd,
    ]
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


# ──────────────────────────────────────────────────────────────────
# Rust batch  - write JSONL, batch into one container exec.
# ──────────────────────────────────────────────────────────────────

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
    pol_path = "/tmp/pol_widen.cedar"
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
    elif res.returncode != 0:
        decision = "ERROR"
    else:
        decision = "ERROR"
    # emit json with idx, decision, raw stdout/stderr tail
    out = {
        "idx": idx,
        "decision": decision,
        "stdout_tail": res.stdout[-400:],
        "stderr_tail": res.stderr[-400:],
        "returncode": res.returncode,
    }
    print(json.dumps(out), flush=True)
'''


def run_rust_batch(tuples: list[dict[str, Any]], timeout: int = 1800) -> dict[str, dict[str, Any]]:
    input_path = HUNT_DIR / "_rust_input.jsonl"
    with open(input_path, "w") as f:
        for t in tuples:
            f.write(json.dumps({
                "idx": t["idx"],
                "principal": t["principal"],
                "action": t["action"],
                "resource": t["resource"],
                "policy": t["policy"],
            }) + "\n")
    runner_path = HUNT_DIR / "_rust_runner.py"
    runner_path.write_text(RUST_RUNNER_SCRIPT)

    proc = run_in_image(
        ["python3",
         "/work/experiments/phase_c_diff/bug-hunt-2026-04-25/_rust_runner.py",
         "/work/experiments/phase_c_diff/bug-hunt-2026-04-25/_rust_input.jsonl",
         CONTAINER_SCHEMA,
         CONTAINER_ENTITIES],
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
        print(f"  rust batch produced no output. stderr tail: {proc.stderr[-1000:]}", file=sys.stderr)
    return out


# ──────────────────────────────────────────────────────────────────
# Go batch  - pipe tuples to harness binary, capture decision + error
# ──────────────────────────────────────────────────────────────────

GO_HARNESS_DIR = HUNT_DIR / "go_harness"
GO_HARNESS_DIR.mkdir(exist_ok=True)

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
		// capture eval errors as "diagnostic"
		var diagStr string
		for _, e := range diag.Errors {
			diagStr += e.Message + "; "
		}
		enc.Encode(Result{Idx: t.Idx, Decision: decision, Diagnostic: diagStr})
	}
}
'''

GO_HARNESS_MOD = """\
module kairos-cedar-diff/widened-go-harness

go 1.24

require github.com/cedar-policy/cedar-go v0.0.0

replace github.com/cedar-policy/cedar-go => /work/cedar-go
"""


def build_go_harness() -> bool:
    (GO_HARNESS_DIR / "go.mod").write_text(GO_HARNESS_MOD)
    (GO_HARNESS_DIR / "main.go").write_text(GO_HARNESS_MAIN)
    proc = run_in_image(
        ["bash", "-c",
         "cd /work/experiments/phase_c_diff/bug-hunt-2026-04-25/go_harness && "
         "GOFLAGS='-mod=mod -buildvcs=false' go mod tidy >/dev/null 2>&1 && "
         "GOFLAGS='-mod=mod -buildvcs=false' go build -o /tmp/widened-harness . 2>&1"],
        timeout=180,
    )
    if proc.returncode != 0:
        print("Go harness build failed:")
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])
        return False
    return True


def run_go_batch(tuples: list[dict[str, Any]], timeout: int = 600) -> dict[str, dict[str, Any]]:
    payload = "\n".join(
        json.dumps({
            "idx": t["idx"],
            "principal": t["principal"],
            "action": t["action"],
            "resource": t["resource"],
            "policy": t["policy"],
        }) for t in tuples
    )
    payload_path = HUNT_DIR / "_go_input.jsonl"
    payload_path.write_text(payload)

    cmd = (
        "cd /work/experiments/phase_c_diff/bug-hunt-2026-04-25/go_harness && "
        "GOFLAGS='-mod=mod -buildvcs=false' go build -o /tmp/widened-harness . >/dev/null 2>&1 && "
        f"/tmp/widened-harness {CONTAINER_ENTITIES} "
        f"< /work/experiments/phase_c_diff/bug-hunt-2026-04-25/_go_input.jsonl"
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
        print(f"  go batch produced no output. stderr tail: {proc.stderr[-1000:]}", file=sys.stderr)
    return out


# ──────────────────────────────────────────────────────────────────
# Classification
# ──────────────────────────────────────────────────────────────────

def classify(rd: dict | None, gd: dict | None) -> tuple[str, dict]:
    """Returns (label, debug-info). Labels:
      agreement_allow, agreement_deny, agreement_both_reject,
      semantic_disagreement (allow vs deny  - paper grade),
      evaluator_disagreement (one accepts, one rejects  - likely paper grade),
      generator_artifact (both reject for different reasons  - log only),
      missing (one runner failed to produce output)
    """
    if rd is None or gd is None:
        return "missing", {"rust": rd, "go": gd}
    rdec = rd.get("decision")
    gdec = gd.get("decision")
    # IMPORTANT: cedar CLI exits with rc=2 on every Deny (not only on errors),
    # so rc alone is not a reliable error signal. The reliable Rust-error
    # marker is the substring "error while evaluating" in stderr (covers
    # ipaddr/decimal/datetime extension parse failures, runtime arithmetic
    # overflow, and entity-attr lookups).
    r_stderr = rd.get("stderr_tail", "") or ""
    r_stdout = rd.get("stdout_tail", "") or ""
    r_err = (
        rdec == "ERROR"
        or "error while evaluating" in (r_stderr + r_stdout)
        or "evaluation error" in (r_stderr + r_stdout)
        or "failed to parse" in (r_stderr + r_stdout)
    )
    # cedar-go puts ext-type parse failures in `diagnostic`, not `error`.
    g_diag = gd.get("diagnostic", "") or ""
    g_err = (
        bool(gd.get("error"))
        or gdec == "ERROR"
        or bool(g_diag.strip())
    )

    if r_err and g_err:
        return "agreement_both_reject", {"rust_err": r_stderr or r_stdout, "go_err": gd.get("error") or gd.get("diagnostic")}
    if r_err and not g_err:
        # Rust errored at extension parse; Go reached a decision. Sub-classify
        # by the authorization decision: if Go's decision is Deny, the
        # *authorisation outcomes match* (Cedar maps eval-error in `permit-when`
        # to "policy not satisfied", so Rust → Deny; Go also → Deny because
        # the boolean condition was false). That's an "asymmetric_path"  - both
        # implementations land on Deny but for different reasons. Still useful
        # to flag, but it's NOT a paper-grade decision-flip.
        if gdec == "Deny":
            return "asymmetric_path_both_deny", {"rust_err": r_stderr or r_stdout, "go_decision": gdec}
        # Go says Allow, Rust errored → outcomes diverge → paper-grade.
        return "evaluator_disagreement", {"rust_err": r_stderr or r_stdout, "go_decision": gdec}
    if not r_err and g_err:
        if rdec == "Deny":
            return "asymmetric_path_both_deny", {"rust_decision": rdec, "go_err": gd.get("error") or gd.get("diagnostic")}
        return "evaluator_disagreement", {"rust_decision": rdec, "go_err": gd.get("error") or gd.get("diagnostic")}
    # Both succeeded
    if rdec == gdec:
        return f"agreement_{rdec.lower()}", {}
    return "semantic_disagreement", {"rust_decision": rdec, "go_decision": gdec}


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shape", default=None,
                        help="Run only this shape; default = all shapes.")
    parser.add_argument("--out", default=str(HUNT_DIR / "results.jsonl"),
                        help="Output JSONL of (tuple, rust, go, classification).")
    parser.add_argument("--summary", default=str(HUNT_DIR / "SUMMARY.md"),
                        help="Markdown summary path.")
    args = parser.parse_args()

    if args.shape:
        if args.shape not in ALL_SHAPES:
            print(f"Unknown shape: {args.shape}. Choices: {list(ALL_SHAPES.keys())}")
            return 1
        tuples = []
        for t in ALL_SHAPES[args.shape]:
            t = dict(t)
            t["shape"] = args.shape
            t["idx"] = f"{args.shape}__{t['sample_id']}"
            tuples.append(t)
    else:
        tuples = all_tuples()

    print(f"[bug-hunt] {len(tuples)} tuples across "
          f"{len({t['shape'] for t in tuples})} shapes")

    print("[bug-hunt] building Go harness ...")
    t0 = time.monotonic()
    if not build_go_harness():
        return 1
    print(f"  built in {time.monotonic()-t0:.1f}s")

    print("[bug-hunt] running Go batch ...")
    t0 = time.monotonic()
    go_results = run_go_batch(tuples, timeout=900)
    print(f"  Go: {len(go_results)} decisions in {time.monotonic()-t0:.1f}s")

    print("[bug-hunt] running Rust batch ...")
    t0 = time.monotonic()
    rust_results = run_rust_batch(tuples, timeout=3600)
    print(f"  Rust: {len(rust_results)} decisions in {time.monotonic()-t0:.1f}s")

    # Write per-tuple results
    out_path = Path(args.out)
    rows = []
    counts: dict[str, dict[str, int]] = {}
    for t in tuples:
        rd = rust_results.get(t["idx"])
        gd = go_results.get(t["idx"])
        label, dbg = classify(rd, gd)
        row = {
            "idx": t["idx"],
            "shape": t["shape"],
            "sample_id": t["sample_id"],
            "policy": t["policy"],
            "principal": t["principal"],
            "action": t["action"],
            "resource": t["resource"],
            "rust": rd,
            "go": gd,
            "classification": label,
            "diff_debug": dbg,
        }
        rows.append(row)
        c = counts.setdefault(t["shape"], {})
        c[label] = c.get(label, 0) + 1

    with open(out_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Surface disagreements + write per-disagreement files
    disagree_dir = HUNT_DIR / "disagreements"
    disagree_dir.mkdir(exist_ok=True)
    disagreements = [r for r in rows if r["classification"] in {"semantic_disagreement", "evaluator_disagreement"}]
    for r in disagreements:
        shape_dir = disagree_dir / r["shape"]
        shape_dir.mkdir(exist_ok=True)
        with open(shape_dir / f"{r['sample_id']}.json", "w") as f:
            json.dump(r, f, indent=2, ensure_ascii=False)

    # Summary
    print("\n" + "=" * 72)
    print("  WIDENED BUG-HUNT SUMMARY")
    print("=" * 72)
    print(f"  Total tuples: {len(rows)}")
    by_label: dict[str, int] = {}
    for r in rows:
        by_label[r["classification"]] = by_label.get(r["classification"], 0) + 1
    for label, n in sorted(by_label.items()):
        print(f"  {label:30s}: {n}")
    print()
    print("  Per-shape:")
    for shape, c in sorted(counts.items()):
        total = sum(c.values())
        diss = c.get("semantic_disagreement", 0) + c.get("evaluator_disagreement", 0)
        print(f"    {shape:30s} N={total:4d}  diss={diss}  {c}")

    if disagreements:
        print(f"\n  {len(disagreements)} disagreements written to {disagree_dir}")
        for r in disagreements[:10]:
            print(f"    {r['idx']}  → {r['classification']}")
            print(f"      policy: {r['policy'][:120]}")
            print(f"      rust  : {(r['rust'] or {}).get('decision')!s:<8} {((r['rust'] or {}).get('stderr_tail') or (r['rust'] or {}).get('stdout_tail') or '')[-100:]}")
            print(f"      go    : {(r['go'] or {}).get('decision')!s:<8} {((r['go'] or {}).get('error') or (r['go'] or {}).get('diagnostic') or '')[-100:]}")

    # Markdown summary
    summary_path = Path(args.summary)
    with open(summary_path, "w") as f:
        f.write(f"# Widened Bug-Hunt Summary  - 2026-04-25\n\n")
        f.write(f"- Total tuples: {len(rows)}\n")
        f.write(f"- Tools: cedar-policy-cli 4.10.0 (Rust) vs cedar-go v1.6.0 (HEAD)\n")
        f.write(f"- Image: `{IMAGE}`\n\n")
        f.write(f"## Aggregate by classification\n\n")
        f.write("| classification | count |\n|---|---|\n")
        for label, n in sorted(by_label.items()):
            f.write(f"| {label} | {n} |\n")
        f.write(f"\n## Per-shape breakdown\n\n")
        f.write("| shape | N | semantic_diss | evaluator_diss | both_reject | agreement |\n")
        f.write("|---|---|---|---|---|---|\n")
        for shape, c in sorted(counts.items()):
            total = sum(c.values())
            sd = c.get("semantic_disagreement", 0)
            ed = c.get("evaluator_disagreement", 0)
            br = c.get("agreement_both_reject", 0)
            ag = c.get("agreement_allow", 0) + c.get("agreement_deny", 0)
            f.write(f"| {shape} | {total} | {sd} | {ed} | {br} | {ag} |\n")
        if disagreements:
            f.write(f"\n## Disagreements ({len(disagreements)})\n\n")
            for r in disagreements:
                f.write(f"### `{r['idx']}`  - {r['classification']}\n\n")
                f.write(f"```cedar\n{r['policy']}\n```\n\n")
                f.write(f"- principal: `{r['principal']}`\n")
                f.write(f"- action: `{r['action']}`\n")
                f.write(f"- resource: `{r['resource']}`\n")
                f.write(f"- rust: `{(r['rust'] or {}).get('decision')}`  - `{((r['rust'] or {}).get('stderr_tail') or (r['rust'] or {}).get('stdout_tail') or '').strip()[:300]}`\n")
                f.write(f"- go: `{(r['go'] or {}).get('decision')}`  - `{((r['go'] or {}).get('error') or (r['go'] or {}).get('diagnostic') or '').strip()[:300]}`\n\n")
    print(f"\n  summary → {summary_path}")
    print(f"  results → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
