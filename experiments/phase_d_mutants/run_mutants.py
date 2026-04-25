"""
experiments/phase_d_mutants/run_mutants.py — seeded-mutant discriminative
power study for the §8 differential pipeline.

For each mutant patch under experiments/phase_d_mutants/mutants/, this
script:

  1. Copies cedar-go to /tmp/cedar-go-<MUTANT_ID>.
  2. Applies the patch with `patch -p1`.
  3. Runs the §8 pipeline (sample N tuples, build the Go harness against
     the mutated cedar-go, run Rust + Go authorize, diff verdicts).
  4. Records per-mutant disagreement count and rate.
  5. Reverts the patch (deletes the temp copy).

Tuples + Rust verdicts are computed once and reused across mutants
(only the Go side changes), since the generator and the spec
implementation are not mutated.

The run wraps everything in a `kairos.session` with run_subtype
"differential_test" so events land in sdk_agent_events.

Usage:
    python3 experiments/phase_d_mutants/run_mutants.py [--n 1000]
                                                      [--mutants M1,M3]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import kairos
import kairos.trace as ktrace

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PHASE_D = REPO_ROOT / "experiments" / "phase_d_mutants"
PHASE_C = REPO_ROOT / "experiments" / "phase_c_diff"
MUTANT_DIR = PHASE_D / "mutants"
OUTPUT_DIR = PHASE_D / "outputs"

# Allow caller to override cedar-full source — defaults to the worktree's
# own cedar-full but can point at the parent repo where the Lean build
# cache lives so we don't have to rebuild measure-diff.
CEDAR_FULL_SRC = Path(os.environ.get(
    "KAIROS_MUTANTS_CEDAR_FULL_SRC",
    str(REPO_ROOT / "cedar-full"),
))

IMAGE = os.environ.get("KAIROS_CEDAR_IMAGE", "ghcr.io/athanor-ai/kairos-cedar:latest")


def _sha12(b: bytes | str) -> str:
    if isinstance(b, str):
        b = b.encode("utf-8")
    return hashlib.sha256(b).hexdigest()[:12]


_EMIT_SEQUENCE = [0]


def _emit(sink, sess, event_type: str, payload: dict) -> None:
    """Best-effort SDK trace emit using TraceEvent dataclass.
    Mirrors the pattern in experiments/phase_c_diff/run_diff.py.
    """
    if sink is None:
        return
    try:
        from kairos.trace import TraceEvent
        run_id = (getattr(sess, "run_id", None)
                  or getattr(sess, "session_id", None)
                  or getattr(sess, "task_id", "unknown"))
        _EMIT_SEQUENCE[0] += 1
        event = TraceEvent(
            run_id=run_id,
            run_type="sdk_orchestration",
            run_subtype="differential_test",
            event_type=event_type,
            sequence=_EMIT_SEQUENCE[0],
            payload=payload,
        )
        sink.emit(event)
    except Exception as e:
        print(f"      WARN: emit failed for event_type={event_type}: {e}",
              file=sys.stderr)


# ── Fixed schema / entities (same as phase_c_diff) ──────────────────────

FIXED_SCHEMA_TEXT = """\
entity User;
entity Document;
entity Photo;

action view, edit, admin appliesTo {
    principal: User,
    resource: [Document, Photo],
};
"""

FIXED_ENTITIES = [
    {"uid": {"type": "User", "id": "alice"}, "attrs": {}, "parents": []},
    {"uid": {"type": "User", "id": "bob"}, "attrs": {}, "parents": []},
    {"uid": {"type": "User", "id": "carol"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Document", "id": "doc1"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Document", "id": "doc2"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Photo", "id": "photo1"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Action", "id": "view"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Action", "id": "edit"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Action", "id": "admin"}, "attrs": {}, "parents": []},
]


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
	Idx      string `json:"idx"`
	Decision string `json:"decision"`
	Error    string `json:"error,omitempty"`
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
			enc.Encode(Result{Idx: t.Idx, Error: fmt.Sprintf("policy parse: %v", err)})
			continue
		}

		req := cedar.Request{
			Principal: ps,
			Action:    act,
			Resource:  res,
			Context:   types.NewRecord(nil),
		}

		dec, _ := policies.IsAuthorized(entities, req)
		decision := "Deny"
		if dec == cedar.Allow {
			decision = "Allow"
		}
		enc.Encode(Result{Idx: t.Idx, Decision: decision})
	}
}
'''

GO_HARNESS_MOD = """\
module kairos-cedar-mutant/go-harness

go 1.24

require github.com/cedar-policy/cedar-go v0.0.0

replace github.com/cedar-policy/cedar-go => /work/cedar-go
"""


# ── Docker invocation helpers ────────────────────────────────────────────

def _docker_run(
    cmd: list[str],
    *,
    cedar_go_overlay: str | None = None,
    workdir: str = "/work",
    timeout: int = 600,
    extra_volumes: list[tuple[str, str]] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command inside the container.

    cedar_go_overlay: if set, mount this host path at /work/cedar-go,
                      shadowing the worktree's empty cedar-go submodule.
    """
    argv = [
        "docker", "run", "--rm",
        "-v", f"{REPO_ROOT}:/work",
        "-v", f"{CEDAR_FULL_SRC}:/work/cedar-full",
    ]
    if cedar_go_overlay is not None:
        argv += ["-v", f"{cedar_go_overlay}:/work/cedar-go"]
    if extra_volumes:
        for host, container in extra_volumes:
            argv += ["-v", f"{host}:{container}"]
    argv += ["-w", workdir, IMAGE, *cmd]
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


# ── Lean generator ───────────────────────────────────────────────────────

def sample_tuples(n: int, timeout: int = 300) -> list[dict[str, str]]:
    """Run measure-diff inside the container and parse output lines."""
    proc = _docker_run(
        ["bash", "-c", f"cd /work/cedar-full && .lake/build/bin/measure-diff {n}"],
        timeout=timeout,
    )
    if proc.returncode != 0:
        print("ERROR: measure-diff failed:")
        print(proc.stderr[-1000:])
        return []

    tuples = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        idx, principal, action, resource = parts[0], parts[1], parts[2], parts[3]
        policy_text = "\t".join(parts[4:])
        tuples.append({
            "idx": idx,
            "principal": principal,
            "action": action,
            "resource": resource,
            "policy": policy_text,
        })
    return tuples


# ── Fixtures ─────────────────────────────────────────────────────────────

def setup_fixtures() -> tuple[str, str]:
    """Write schema + entities under the worktree."""
    fixtures_dir = PHASE_D / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    schema_path = fixtures_dir / "schema.cedarschema"
    schema_path.write_text(FIXED_SCHEMA_TEXT)

    entities_path = fixtures_dir / "entities.json"
    entities_path.write_text(json.dumps(FIXED_ENTITIES, indent=2))

    return ("/work/experiments/phase_d_mutants/fixtures/schema.cedarschema",
            "/work/experiments/phase_d_mutants/fixtures/entities.json")


# ── Rust authorize ───────────────────────────────────────────────────────

def run_rust_batch(
    tuples: list[dict[str, str]],
    schema_file: str,
    entities_file: str,
    timeout: int = 600,
) -> dict[str, str]:
    """Run cedar authorize for all tuples in a single container invocation.
    Same script as phase_c_diff but writes into the phase_d workspace."""
    rust_input_path = PHASE_D / "_rust_input.jsonl"
    with open(rust_input_path, "w") as f:
        for t in tuples:
            f.write(json.dumps(t) + "\n")

    script = r"""
import json, subprocess, sys, os

input_path = "/work/experiments/phase_d_mutants/_rust_input.jsonl"
schema_file = sys.argv[1]
entities_file = sys.argv[2]

lines = open(input_path).readlines()
for line in lines:
    line = line.strip()
    if not line:
        continue
    t = json.loads(line)
    idx = t["idx"]
    policy = t["policy"]
    p_parts = t["principal"].split("::")
    a_parts = t["action"].split("::")
    r_parts = t["resource"].split("::")

    pol_path = f"/tmp/pol_{idx}.cedar"
    with open(pol_path, "w") as f:
        f.write(policy)

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
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    txt = (result.stdout + result.stderr).upper()
    if "ALLOW" in txt:
        decision = "Allow"
    elif "DENY" in txt:
        decision = "Deny"
    else:
        decision = "ERROR(" + (result.stdout + result.stderr).strip()[:40] + ")"
    print(f"{idx}\t{decision}", flush=True)
"""
    runner_path = PHASE_D / "_rust_runner.py"
    runner_path.write_text(script)

    proc = _docker_run(
        ["python3", "/work/experiments/phase_d_mutants/_rust_runner.py",
         schema_file, entities_file],
        timeout=timeout,
    )

    results = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        idx, decision = line.split("\t", 1)
        results[idx] = decision

    if proc.returncode != 0 and not results:
        print(f"      Rust batch runner stderr: {proc.stderr[-500:]}")

    return results


# ── Mutant management ────────────────────────────────────────────────────

def discover_mutants() -> list[dict[str, str]]:
    """Find all M*/mutant.patch under MUTANT_DIR. Returns list ordered by
    directory name (M1, M2, ...)."""
    mutants = []
    for d in sorted(MUTANT_DIR.iterdir()):
        if not d.is_dir():
            continue
        patch = d / "mutant.patch"
        if not patch.is_file():
            continue
        mutants.append({
            "id": d.name,
            "short_id": d.name.split("_", 1)[0],
            "patch_path": str(patch),
            "readme_path": str(d / "README.md") if (d / "README.md").exists() else "",
        })
    return mutants


def prepare_cedar_go_with_patch(
    cedar_go_src: Path, patch_path: str, mutant_id: str
) -> tuple[Path, str | None]:
    """Copy cedar-go to /tmp/cedar-go-<mutant_id>, apply patch.
    Returns (path, error). If error is non-None the mutant could not be
    applied (compile error is detected later).
    """
    dest = Path(f"/tmp/cedar-go-{mutant_id}")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(cedar_go_src, dest, symlinks=True)
    # Apply patch from inside the dest dir
    proc = subprocess.run(
        ["patch", "-p1", "-i", patch_path],
        cwd=str(dest), capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        return dest, f"patch failed: {proc.stdout[-400:]} {proc.stderr[-400:]}"
    return dest, None


def build_go_harness_for_mutant(cedar_go_overlay: Path) -> tuple[bool, str]:
    """Build the Go harness against a specific cedar-go overlay.

    Returns (ok, log_tail). On compile error returns (False, error_log).
    """
    harness_dir = PHASE_D / "go_harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    (harness_dir / "go.mod").write_text(GO_HARNESS_MOD)
    (harness_dir / "main.go").write_text(GO_HARNESS_MAIN)
    # go.sum may be stale across mutants; rebuild from clean.
    sumf = harness_dir / "go.sum"
    if sumf.exists():
        sumf.unlink()

    proc = _docker_run(
        [
            "bash", "-c",
            "cd /work/experiments/phase_d_mutants/go_harness && "
            "GOFLAGS='-mod=mod -buildvcs=false' go mod tidy >/dev/null 2>&1 && "
            "GOFLAGS='-mod=mod -buildvcs=false' go build -o /tmp/diff-harness . 2>&1",
        ],
        cedar_go_overlay=str(cedar_go_overlay),
        timeout=180,
    )
    log = (proc.stdout or "") + (proc.stderr or "")
    return (proc.returncode == 0, log[-2000:])


def run_go_batch_with_overlay(
    tuples: list[dict[str, str]],
    entities_file: str,
    cedar_go_overlay: Path,
    timeout: int = 600,
) -> dict[str, str]:
    """Run the Go harness against a mutated cedar-go via volume overlay."""
    stdin_lines = []
    for t in tuples:
        stdin_lines.append(json.dumps({
            "idx": t["idx"],
            "principal": t["principal"],
            "action": t["action"],
            "resource": t["resource"],
            "policy": t["policy"],
        }))
    stdin_payload = "\n".join(stdin_lines)

    payload_host = PHASE_D / "_go_input.jsonl"
    payload_host.write_text(stdin_payload, encoding="utf-8")

    cmd = (
        "cd /work/experiments/phase_d_mutants/go_harness && "
        "GOFLAGS='-mod=mod -buildvcs=false' go build -o /tmp/diff-harness . >/dev/null 2>&1 && "
        f"/tmp/diff-harness {entities_file} < /work/experiments/phase_d_mutants/_go_input.jsonl"
    )
    proc = _docker_run(
        ["bash", "-c", cmd],
        cedar_go_overlay=str(cedar_go_overlay),
        timeout=timeout,
    )

    results = {}
    if proc.returncode != 0 and not proc.stdout.strip():
        print("      Go harness run failed:")
        print(proc.stderr[-2000:])
        return {}

    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            idx = obj.get("idx", "?")
            if "error" in obj:
                results[idx] = f"ERROR({obj['error'][:60]})"
            else:
                results[idx] = obj.get("decision", "ERROR(no decision)")
        except json.JSONDecodeError:
            pass
    return results


# ── Disagreement bucketing ───────────────────────────────────────────────

def shape_of(policy: str) -> str:
    """Coarse shape label for a Cedar policy: which top-level construct
    dominates the when clause. Best-effort, used only for the
    per-shape disagreement breakdown."""
    p = policy.lower()
    is_permit = p.startswith("permit")
    head = "permit" if is_permit else "forbid"
    if "if " in p and " then " in p and " else " in p:
        return f"{head}+ite"
    if " && " in p:
        return f"{head}+and"
    if " || " in p:
        return f"{head}+or"
    if " in " in p:
        return f"{head}+in"
    if " == " in p:
        return f"{head}+eq"
    if " when " in p:
        return f"{head}+when_other"
    return f"{head}+scope_only"


def bucket_disagreements(disagreements: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for d in disagreements:
        s = shape_of(d.get("policy", ""))
        counts[s] = counts.get(s, 0) + 1
    return counts


# ── Main loop ────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seeded-mutant discriminative-power study"
    )
    parser.add_argument("--n", type=int, default=1000,
                        help="Tuples sampled from CedarFull.PolicyGen")
    parser.add_argument("--mutants", type=str, default="",
                        help="Comma-separated mutant short-ids (e.g. M1,M3). "
                             "Empty = all.")
    parser.add_argument("--rust-timeout", type=int, default=600)
    parser.add_argument("--go-timeout", type=int, default=600)
    parser.add_argument("--no-session", action="store_true")
    args = parser.parse_args()

    sink = ktrace.default_sink_from_env() if not args.no_session else None
    task_id = f"ath-cedar-mutant-study-n{args.n}"
    session_cm = kairos.session(
        task_id=task_id,
        trace_sink=sink,
        vertical="auth",
        run_type="sdk_orchestration",
        run_subtype="differential_test",
        name_for_display=f"Cedar seeded-mutant study N={args.n}",
    )

    with session_cm as sess:
        sid = (getattr(sess, "session_id", None)
               or getattr(sess, "task_id", task_id))
        print(f"[mutants] session_id={sid} sink={type(sink).__name__}")
        return _run_study(args, sess, sink)


def _run_study(args, sess, sink) -> int:
    print("=" * 72)
    print(f"  kairos-cedar Phase D seeded-mutant study N={args.n}")
    print(f"  image: {IMAGE}")
    print(f"  cedar-full src: {CEDAR_FULL_SRC}")
    print("=" * 72)

    t_total = time.monotonic()

    # Discover mutants
    all_mutants = discover_mutants()
    if args.mutants:
        wanted = set(args.mutants.split(","))
        mutants = [m for m in all_mutants if m["short_id"] in wanted]
    else:
        mutants = all_mutants

    print(f"\n[setup] {len(mutants)} mutants discovered: "
          f"{[m['short_id'] for m in mutants]}")

    _emit(sink, sess, "run_start", {
        "n_target": args.n,
        "image": IMAGE,
        "cedar_full_src": str(CEDAR_FULL_SRC),
        "n_mutants": len(mutants),
        "mutant_ids": [m["short_id"] for m in mutants],
    })

    # 1. Fixtures
    print("\n[1/3] Writing fixtures ...")
    _emit(sink, sess, "phase_start", {"phase": "fixtures"})
    container_schema, container_entities = setup_fixtures()
    _emit(sink, sess, "phase_complete", {
        "phase": "fixtures",
        "schema_path": container_schema,
        "entities_path": container_entities,
        "schema_sha12": _sha12(FIXED_SCHEMA_TEXT),
    })

    # 2. Sample tuples (once, reused across all mutants)
    print(f"\n[2/3] Sampling {args.n} tuples from CedarFull.PolicyGen ...")
    _emit(sink, sess, "phase_start",
          {"phase": "sample_tuples", "n_target": args.n})
    t_sample = time.monotonic()
    tuples = sample_tuples(args.n)
    elapsed_sample = time.monotonic() - t_sample
    if not tuples:
        _emit(sink, sess, "phase_error",
              {"phase": "sample_tuples", "error": "no tuples"})
        _emit(sink, sess, "run_complete",
              {"status": "failed", "reason": "no_tuples"})
        print("FAIL: no tuples generated")
        return 1
    print(f"      Generated {len(tuples)} tuples in {elapsed_sample:.1f}s")
    _emit(sink, sess, "phase_complete", {
        "phase": "sample_tuples",
        "n_generated": len(tuples),
        "n_target": args.n,
        "elapsed_sec": elapsed_sample,
    })

    # 3. Run Rust authorize once (the spec is invariant under mutation)
    print(f"\n[3/3] Running Rust cedar authorize on {len(tuples)} tuples ...")
    _emit(sink, sess, "phase_start",
          {"phase": "rust_per_tuple", "n_tuples": len(tuples)})
    t_rust = time.monotonic()
    rust_decisions = run_rust_batch(
        tuples, container_schema, container_entities,
        timeout=args.rust_timeout,
    )
    elapsed_rust = time.monotonic() - t_rust
    print(f"      {len(rust_decisions)} decisions in {elapsed_rust:.1f}s")
    _emit(sink, sess, "phase_complete", {
        "phase": "rust_per_tuple",
        "n_decisions": len(rust_decisions),
        "n_tuples": len(tuples),
        "elapsed_sec": elapsed_rust,
    })

    # 4. Per-mutant: copy cedar-go, apply patch, build harness, run go,
    #    compare to rust, revert.
    cedar_go_src = REPO_ROOT / "cedar-go"
    if not (cedar_go_src / "go.mod").exists():
        # In a worktree, cedar-go submodule may not be initialised. Fall
        # back to the parent repo's cedar-go.
        alt = Path(os.environ.get(
            "KAIROS_MUTANTS_CEDAR_GO_SRC",
            "/home/azureuser/agents/platform/kairos-cedar/cedar-go",
        ))
        if (alt / "go.mod").exists():
            cedar_go_src = alt

    print(f"\n[mutants] cedar-go src: {cedar_go_src}")

    per_mutant: list[dict[str, Any]] = []
    for m in mutants:
        mid = m["short_id"]
        print("\n" + "-" * 72)
        print(f"  Mutant {mid} ({m['id']})")
        print("-" * 72)

        _emit(sink, sess, "phase_start", {
            "phase": "mutant_run",
            "mutant_id": mid,
            "mutant_dir": m["id"],
        })
        t_m = time.monotonic()

        # Apply patch
        try:
            overlay, patch_err = prepare_cedar_go_with_patch(
                cedar_go_src, m["patch_path"], mid,
            )
        except Exception as e:
            patch_err = f"copy/patch threw: {e}"
            overlay = None

        if patch_err:
            print(f"      PATCH ERROR: {patch_err}")
            _emit(sink, sess, "phase_error", {
                "phase": "mutant_run",
                "mutant_id": mid,
                "error": "patch_failed",
                "detail": patch_err[:1000],
            })
            per_mutant.append({
                "mutant_id": mid,
                "mutant_dir": m["id"],
                "status": "patch_failed",
                "error": patch_err[:1000],
            })
            _emit(sink, sess, "mutant_result", {
                "mutant_id": mid,
                "n_disagreements": 0,
                "disagreement_rate": None,
                "wall_time_sec": time.monotonic() - t_m,
                "status": "patch_failed",
            })
            continue

        # Build harness
        ok, log_tail = build_go_harness_for_mutant(overlay)
        if not ok:
            print(f"      BUILD ERROR (mutant {mid} induces compile error)")
            print(log_tail)
            _emit(sink, sess, "phase_error", {
                "phase": "mutant_run",
                "mutant_id": mid,
                "error": "compile_failed",
                "detail": log_tail[:1500],
            })
            per_mutant.append({
                "mutant_id": mid,
                "mutant_dir": m["id"],
                "status": "compile_failed",
                "compile_log_tail": log_tail[-500:],
                "n_disagreements": 0,
                "disagreement_rate": None,
                "wall_time_sec": time.monotonic() - t_m,
            })
            _emit(sink, sess, "mutant_result", {
                "mutant_id": mid,
                "n_disagreements": 0,
                "disagreement_rate": None,
                "wall_time_sec": time.monotonic() - t_m,
                "status": "compile_failed",
            })
            shutil.rmtree(overlay, ignore_errors=True)
            continue

        # Go batch
        t_go = time.monotonic()
        go_decisions = run_go_batch_with_overlay(
            tuples, container_entities, overlay,
            timeout=args.go_timeout,
        )
        elapsed_go = time.monotonic() - t_go
        print(f"      Go batch: {len(go_decisions)} decisions in "
              f"{elapsed_go:.1f}s")

        # Compare
        agreements = 0
        disagreements: list[dict] = []
        compared = 0
        for t in tuples:
            idx = t["idx"]
            rd = rust_decisions.get(idx, "missing")
            gd = go_decisions.get(idx, "missing")
            if rd.startswith("ERROR") or rd == "missing":
                continue
            if gd.startswith("ERROR") or gd == "missing":
                continue
            compared += 1
            if rd == gd:
                agreements += 1
            else:
                disagreements.append({
                    "idx": idx,
                    "principal": t["principal"],
                    "action": t["action"],
                    "resource": t["resource"],
                    "policy": t["policy"],
                    "rust": rd,
                    "go": gd,
                })

        rate = (len(disagreements) / compared) if compared > 0 else None
        per_shape = bucket_disagreements(disagreements)

        wall_m = time.monotonic() - t_m
        print(f"      Compared          : {compared}")
        print(f"      Agreements        : {agreements}")
        print(f"      Disagreements     : {len(disagreements)}")
        if rate is not None:
            print(f"      Disagreement rate : {rate:.4f}")
        print(f"      Wall              : {wall_m:.1f}s")
        if per_shape:
            print(f"      Per-shape breakdown (top 5):")
            for k, v in sorted(per_shape.items(), key=lambda kv: -kv[1])[:5]:
                print(f"          {k}: {v}")

        # Persist disagreement corpus per mutant (capped at 200 to avoid
        # huge JSONL on M1 ~100% disagreement)
        cap = 200
        dis_path = OUTPUT_DIR / f"disagreements_{mid}.jsonl"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(dis_path, "w") as f:
            for d in disagreements[:cap]:
                f.write(json.dumps(d) + "\n")

        per_mutant.append({
            "mutant_id": mid,
            "mutant_dir": m["id"],
            "status": "ok",
            "n_compared": compared,
            "n_agreements": agreements,
            "n_disagreements": len(disagreements),
            "disagreement_rate": rate,
            "wall_time_sec": wall_m,
            "go_elapsed_sec": elapsed_go,
            "per_shape_disagreements": per_shape,
            "disagreement_sample_path": str(dis_path),
            "disagreement_sample_capped": (len(disagreements) > cap),
        })

        _emit(sink, sess, "phase_complete", {
            "phase": "mutant_run",
            "mutant_id": mid,
            "n_compared": compared,
            "n_agreements": agreements,
            "n_disagreements": len(disagreements),
            "disagreement_rate": rate,
            "wall_time_sec": wall_m,
            "per_shape_disagreements": per_shape,
        })
        _emit(sink, sess, "mutant_result", {
            "mutant_id": mid,
            "n_disagreements": len(disagreements),
            "disagreement_rate": rate,
            "n_compared": compared,
            "wall_time_sec": wall_m,
            "per_shape_disagreements": per_shape,
            "status": "ok",
        })

        # Revert: just delete the temp copy.
        shutil.rmtree(overlay, ignore_errors=True)

    # ── Summary ──────────────────────────────────────────────────────────

    total_elapsed = time.monotonic() - t_total

    summary = {
        "task_id": f"ath-cedar-mutant-study-n{args.n}",
        "n_target": args.n,
        "n_sampled": len(tuples),
        "n_rust_decisions": len(rust_decisions),
        "image": IMAGE,
        "cedar_full_src": str(CEDAR_FULL_SRC),
        "wall_time_total_sec": total_elapsed,
        "phase_timings_sec": {
            "sample_tuples": elapsed_sample,
            "rust_per_tuple": elapsed_rust,
        },
        "per_mutant": per_mutant,
        "blind_spots": [
            m for m in per_mutant
            if m.get("status") == "ok"
            and (m.get("disagreement_rate") or 0) == 0.0
        ],
        "compile_failures": [
            m for m in per_mutant if m.get("status") == "compile_failed"
        ],
        "patch_failures": [
            m for m in per_mutant if m.get("status") == "patch_failed"
        ],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = OUTPUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    print("\n" + "=" * 72)
    print("  PHASE D SEEDED-MUTANT STUDY — SUMMARY")
    print("=" * 72)
    print(f"  N sampled       : {len(tuples)}")
    print(f"  Mutants run     : {len(mutants)}")
    print(f"  Wall (total)    : {total_elapsed:.1f}s")
    print(f"  Summary         : {summary_path}")
    print()
    for m in per_mutant:
        if m.get("status") == "ok":
            r = m["disagreement_rate"]
            print(f"  {m['mutant_id']}  status=ok  "
                  f"disagreements={m['n_disagreements']}/{m['n_compared']}  "
                  f"rate={r:.4f}" if r is not None
                  else f"  {m['mutant_id']}  status=ok  rate=N/A")
        else:
            print(f"  {m['mutant_id']}  status={m['status']}")

    blind = summary["blind_spots"]
    if blind:
        print(f"\n  BLIND SPOTS (mutants with 0 disagreements): "
              f"{[b['mutant_id'] for b in blind]}")

    _emit(sink, sess, "run_complete", {
        "status": "succeeded",
        "n_target": args.n,
        "n_sampled": len(tuples),
        "n_mutants": len(mutants),
        "n_blind_spots": len(blind),
        "wall_time_total_sec": total_elapsed,
        "per_mutant_summary": [
            {
                "mutant_id": m["mutant_id"],
                "status": m["status"],
                "n_disagreements": m.get("n_disagreements", 0),
                "disagreement_rate": m.get("disagreement_rate"),
            }
            for m in per_mutant
        ],
    })

    return 0


if __name__ == "__main__":
    sys.exit(main())
