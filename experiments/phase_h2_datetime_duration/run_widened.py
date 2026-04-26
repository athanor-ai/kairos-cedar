"""
run_widened.py; execute datetime/duration probe shapes against both
cedar-policy (Rust) and cedar-go and report disagreements.

Usage:
    python3 experiments/phase_h2_datetime_duration/run_widened.py
        [--shape h1_datetime_parse]
        [--out experiments/phase_h2_datetime_duration/results.jsonl]
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
sys.path.insert(0, str(REPO_ROOT / "experiments" / "phase_h2_datetime_duration"))

from widened_shapes import all_tuples, ALL_SHAPES  # noqa: E402

IMAGE = os.environ.get("KAIROS_CEDAR_IMAGE", "ghcr.io/athanor-ai/kairos-cedar:latest")
PHASE_DIR = REPO_ROOT / "experiments" / "phase_h2_datetime_duration"

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

FIXTURES_DIR = PHASE_DIR / "fixtures"
FIXTURES_DIR.mkdir(exist_ok=True)
(FIXTURES_DIR / "schema.cedarschema").write_text(FIXED_SCHEMA_TEXT)
(FIXTURES_DIR / "entities.json").write_text(json.dumps(FIXED_ENTITIES, indent=2))

CONTAINER_SCHEMA = "/work/experiments/phase_h2_datetime_duration/fixtures/schema.cedarschema"
CONTAINER_ENTITIES = "/work/experiments/phase_h2_datetime_duration/fixtures/entities.json"


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
# Rust batch
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
    pol_path = "/tmp/pol_h2.cedar"
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
    input_path = PHASE_DIR / "_rust_input.jsonl"
    with open(input_path, "w") as f:
        for t in tuples:
            f.write(json.dumps({
                "idx": t["idx"],
                "principal": t["principal"],
                "action": t["action"],
                "resource": t["resource"],
                "policy": t["policy"],
            }) + "\n")
    runner_path = PHASE_DIR / "_rust_runner.py"
    runner_path.write_text(RUST_RUNNER_SCRIPT)

    proc = run_in_image(
        ["python3",
         "/work/experiments/phase_h2_datetime_duration/_rust_runner.py",
         "/work/experiments/phase_h2_datetime_duration/_rust_input.jsonl",
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
# Go batch
# ──────────────────────────────────────────────────────────────────

GO_HARNESS_DIR = PHASE_DIR / "go_harness"
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
		var diagStr string
		for _, e := range diag.Errors {
			diagStr += e.Message + "; "
		}
		enc.Encode(Result{Idx: t.Idx, Decision: decision, Diagnostic: diagStr})
	}
}
'''

GO_HARNESS_MOD = """\
module kairos-cedar-diff/h2-go-harness

go 1.24

require github.com/cedar-policy/cedar-go v0.0.0

replace github.com/cedar-policy/cedar-go => /work/cedar-go
"""


def build_go_harness() -> bool:
    (GO_HARNESS_DIR / "go.mod").write_text(GO_HARNESS_MOD)
    (GO_HARNESS_DIR / "main.go").write_text(GO_HARNESS_MAIN)
    proc = run_in_image(
        ["bash", "-c",
         "cd /work/experiments/phase_h2_datetime_duration/go_harness && "
         "GOFLAGS='-mod=mod -buildvcs=false' go mod tidy >/dev/null 2>&1 && "
         "GOFLAGS='-mod=mod -buildvcs=false' go build -o /tmp/h2-harness . 2>&1"],
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
    payload_path = PHASE_DIR / "_go_input.jsonl"
    payload_path.write_text(payload)

    cmd = (
        "cd /work/experiments/phase_h2_datetime_duration/go_harness && "
        "GOFLAGS='-mod=mod -buildvcs=false' go build -o /tmp/h2-harness . >/dev/null 2>&1 && "
        f"/tmp/h2-harness {CONTAINER_ENTITIES} "
        f"< /work/experiments/phase_h2_datetime_duration/_go_input.jsonl"
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
# Classification (mirrors bug-hunt-2026-04-25 logic)
# ──────────────────────────────────────────────────────────────────

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
    g_err = (
        bool(gd.get("error"))
        or gdec == "ERROR"
        or bool(g_diag.strip())
    )

    if r_err and g_err:
        return "agreement_both_reject", {
            "rust_err": (r_stderr or r_stdout)[-200:],
            "go_err": gd.get("error") or gd.get("diagnostic"),
        }
    if r_err and not g_err:
        if gdec == "Deny":
            return "asymmetric_path_both_deny", {
                "rust_err": (r_stderr or r_stdout)[-200:],
                "go_decision": gdec,
            }
        return "evaluator_disagreement", {
            "rust_err": (r_stderr or r_stdout)[-200:],
            "go_decision": gdec,
        }
    if not r_err and g_err:
        if rdec == "Deny":
            return "asymmetric_path_both_deny", {
                "rust_decision": rdec,
                "go_err": gd.get("error") or gd.get("diagnostic"),
            }
        return "evaluator_disagreement", {
            "rust_decision": rdec,
            "go_err": gd.get("error") or gd.get("diagnostic"),
        }
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
    parser.add_argument("--out", default=str(PHASE_DIR / "results.jsonl"),
                        help="Output JSONL path.")
    parser.add_argument("--summary", default=str(PHASE_DIR / "SUMMARY.md"),
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

    print(f"[phase_h2] {len(tuples)} tuples across "
          f"{len({t['shape'] for t in tuples})} shapes")

    print("[phase_h2] building Go harness ...")
    t0 = time.monotonic()
    if not build_go_harness():
        return 1
    print(f"  built in {time.monotonic()-t0:.1f}s")

    print("[phase_h2] running Go batch ...")
    t0 = time.monotonic()
    go_results = run_go_batch(tuples, timeout=900)
    print(f"  Go: {len(go_results)} decisions in {time.monotonic()-t0:.1f}s")

    print("[phase_h2] running Rust batch ...")
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

    # Write per-disagreement files
    disagree_dir = PHASE_DIR / "disagreements"
    disagree_dir.mkdir(exist_ok=True)
    disagreements = [
        r for r in rows
        if r["classification"] in {"semantic_disagreement", "evaluator_disagreement"}
    ]
    for r in disagreements:
        shape_dir = disagree_dir / r["shape"]
        shape_dir.mkdir(exist_ok=True)
        with open(shape_dir / f"{r['sample_id']}.json", "w") as f:
            json.dump(r, f, indent=2, ensure_ascii=False)

    # Print summary
    print("\n" + "=" * 72)
    print("  PHASE H2 DATETIME/DURATION DRIFT SUMMARY")
    print("=" * 72)
    print(f"  Total tuples: {len(rows)}")
    by_label: dict[str, int] = {}
    for r in rows:
        by_label[r["classification"]] = by_label.get(r["classification"], 0) + 1
    for label, n in sorted(by_label.items()):
        print(f"  {label:40s}: {n}")
    print()
    print("  Per-shape:")
    for shape, c in sorted(counts.items()):
        total = sum(c.values())
        diss = c.get("semantic_disagreement", 0) + c.get("evaluator_disagreement", 0)
        print(f"    {shape:35s} N={total:4d}  diss={diss}  {c}")

    if disagreements:
        print(f"\n  {len(disagreements)} disagreements → {disagree_dir}")
        for r in disagreements[:20]:
            print(f"    {r['idx']}  → {r['classification']}")
            print(f"      policy: {r['policy'][:120]}")
            rust_out = ((r.get('rust') or {}).get('stderr_tail') or
                        (r.get('rust') or {}).get('stdout_tail') or '')
            go_out = ((r.get('go') or {}).get('error') or
                      (r.get('go') or {}).get('diagnostic') or '')
            print(f"      rust  : {(r['rust'] or {}).get('decision')!s:<8} {rust_out[-100:]}")
            print(f"      go    : {(r['go'] or {}).get('decision')!s:<8} {go_out[-100:]}")

    # Markdown summary (filled in after reviewing results)
    summary_path = Path(args.summary)
    _write_summary(summary_path, rows, by_label, counts, disagreements, IMAGE)
    print(f"\n  summary → {summary_path}")
    print(f"  results → {out_path}")
    return 0


def _write_summary(
    path: Path,
    rows: list[dict],
    by_label: dict[str, int],
    counts: dict[str, dict[str, int]],
    disagreements: list[dict],
    image: str,
) -> None:
    with open(path, "w") as f:
        f.write("# Phase H2; Datetime/Duration Drift Investigation\n\n")
        f.write("**Purpose:** Empirically test §7.4 prediction; same drift class on datetime + duration.\n\n")
        f.write(f"- Implementations: cedar-policy 4.10.0 (Rust) vs cedar-go v1.6.0 (commit `a9a4b1b`)\n")
        f.write(f"- Image: `{image}`\n")
        f.write(f"- Tuples: {len(rows)}\n\n")

        f.write("## Aggregate by classification\n\n")
        f.write("| classification | count |\n|---|---|\n")
        for label, n in sorted(by_label.items()):
            f.write(f"| {label} | {n} |\n")

        f.write("\n## Per-shape breakdown\n\n")
        f.write("| shape | N | evaluator_diss | semantic_diss | both_reject | agreement |\n")
        f.write("|---|---|---|---|---|---|\n")
        for shape, c in sorted(counts.items()):
            total = sum(c.values())
            ed = c.get("evaluator_disagreement", 0)
            sd = c.get("semantic_disagreement", 0)
            br = c.get("agreement_both_reject", 0)
            ag = sum(v for k, v in c.items() if k.startswith("agreement_") and k != "agreement_both_reject")
            f.write(f"| {shape} | {total} | {ed} | {sd} | {br} | {ag} |\n")

        if disagreements:
            f.write(f"\n## Disagreements ({len(disagreements)})\n\n")
            for r in disagreements:
                f.write(f"### `{r['idx']}`; {r['classification']}\n\n")
                f.write(f"```cedar\n{r['policy']}\n```\n\n")
                rust_out = ((r.get('rust') or {}).get('stderr_tail') or
                            (r.get('rust') or {}).get('stdout_tail') or '').strip()
                go_out = ((r.get('go') or {}).get('error') or
                          (r.get('go') or {}).get('diagnostic') or '').strip()
                f.write(f"- rust decision: `{(r['rust'] or {}).get('decision')}`\n")
                f.write(f"- rust output: `{rust_out[:400]}`\n")
                f.write(f"- go decision: `{(r['go'] or {}).get('decision')}`\n")
                f.write(f"- go output: `{go_out[:400]}`\n\n")
        else:
            f.write("\n## Disagreements\n\nNone found.\n")

        # Predicted-vs-found paragraph (to be reviewed)
        f.write("\n## Predicted-vs-found analysis\n\n")
        eval_diss = [r for r in disagreements if r["classification"] == "evaluator_disagreement"]
        sem_diss = [r for r in disagreements if r["classification"] == "semantic_disagreement"]
        dt_diss = [r for r in disagreements if r["shape"].startswith("h1") or r["shape"].startswith("h3")]
        dur_diss = [r for r in disagreements if r["shape"].startswith("h2")]

        if disagreements:
            f.write(
                f"The §7.4 prediction was that datetime and duration would exhibit the same "
                f"'stdlib superset' drift class as decimal (B2.1) and ipaddr (B2.2). "
                f"The probe found **{len(disagreements)} disagreement(s)** "
                f"({len(eval_diss)} evaluator-level decision-flips, {len(sem_diss)} semantic disagreements): "
                f"{len(dt_diss)} in datetime shapes and {len(dur_diss)} in duration shapes.\n\n"
            )
            if eval_diss:
                f.write(
                    "Decision-flipping disagreements (evaluator_disagreement) indicate that one "
                    "implementation accepted a string the other rejected, producing different "
                    "authorization outcomes. These confirm the §7.4 prediction and constitute "
                    "paper-grade findings.\n\n"
                )
        else:
            f.write(
                "**The §7.4 prediction was NOT confirmed on the inputs probed.** "
                "No decision-flipping disagreements were found in datetime or duration parsing "
                "across the input set tested. The cedar-go datetime parser (hand-rolled, not "
                "delegating to Go stdlib) and cedar-go duration parser (hand-rolled) did not "
                "exhibit the same stdlib-superset pattern seen in decimal (strconv.ParseInt) "
                "and ipaddr (net/netip). "
                "The §7.4 claim must narrow: the 'stdlib superset' architectural pattern held "
                "on the two tested extension types (decimal, ipaddr) and was not confirmed or "
                "refuted on the two remaining types (datetime, duration) by the inputs probed. "
                "Honest narrowing: 'We tested two of four extension types and observed drift; "
                "the prediction for the remaining two was not confirmed on the inputs we exercised.'\n"
            )


if __name__ == "__main__":
    sys.exit(main())
