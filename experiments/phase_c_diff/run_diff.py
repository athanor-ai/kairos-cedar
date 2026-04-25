"""
experiments/phase_c_diff/run_diff.py — §8 Evaluation diff runner.

Samples N (default 1000) tuples from CedarFull.PolicyGen via the
measure-diff Lean binary, then evaluates each tuple against THREE
independent implementations:
  • cedar-policy (Rust reference, v4.3.1+) via `cedar authorize` CLI
  • cedar-go (Go implementation, v1 track HEAD) via a tiny Go harness
  • cedar-lean (cedar-spec mechanised evaluator) via `measure-lean` Lean exe
    — see cedar-full/MeasureLean.lean for the bridge.

With three independent oracles, the §8 0-disagreement result becomes
3-way triangulated consensus: a tuple counts as "consensus" only when
all three implementations agree on Allow / Deny.

Emits a summary: valid-sample rate, three-way consensus rate, pairwise
disagreement counts, disagreement corpus, wall-time per tuple.

Usage:
    python3 experiments/phase_c_diff/run_diff.py [--n N] [--timeout T]

Model after demo/run_demo.py: uses run_in_image() to shell every
toolchain call into the kairos-cedar container.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import kairos
import kairos.trace as ktrace

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
IMAGE = os.environ.get("KAIROS_CEDAR_IMAGE", "ghcr.io/athanor-ai/kairos-cedar:latest")


def _sha12(b: bytes | str) -> str:
    if isinstance(b, str):
        b = b.encode("utf-8")
    return hashlib.sha256(b).hexdigest()[:12]


_EMIT_SEQUENCE = [0]  # mutable single-element list as monotonic counter


def _emit(sink, sess, event_type: str, payload: dict) -> None:
    """Best-effort SDK trace emit. Per Sam 2026-04-25 directive: every meaningful
    callsite should emit so the run is auditable in sdk_agent_events even on
    crash. Swallows errors so a sink hiccup never kills the run, but logs.

    Uses the kairos.trace.TraceEvent dataclass — passing a dict to
    SupabaseTraceSink.emit silently fails validation and drops the event.
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
        print(f"      WARN: emit failed for event_type={event_type}: {e}", file=sys.stderr)

# ── Fixed schema / entities ──────────────────────────────────────────────
#
# We use a fixed Cedar schema matching the generator's fixedSchema:
#   entity User;
#   entity Document;
#   entity Photo;
#   action view, edit, admin appliesTo { principal: User, resource: [Document, Photo] };
#
# Entities include 3 principals + 3 resources so all requests resolve.

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
    # Action entities are implicit in the schema, but cedar-go may need them listed.
    {"uid": {"type": "Action", "id": "view"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Action", "id": "edit"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Action", "id": "admin"}, "attrs": {}, "parents": []},
]


def run_in_image(
    cmd: list[str], *, workdir: str = "/work", timeout: int = 600
) -> subprocess.CompletedProcess[str]:
    """Shell a command inside the kairos-cedar container with the repo mounted."""
    argv = [
        "docker", "run", "--rm",
        "-v", f"{REPO_ROOT}:/work",
        "-w", workdir,
        IMAGE,
        *cmd,
    ]
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


# ── Lean generator ───────────────────────────────────────────────────────

def sample_tuples(n: int, timeout: int = 120) -> list[dict[str, str]]:
    """Run measure-diff inside the container and parse output lines."""
    proc = run_in_image(
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
        policy_text = "\t".join(parts[4:])  # remainder is policy text
        tuples.append({
            "idx": idx,
            "principal": principal,
            "action": action,
            "resource": resource,
            "policy": policy_text,
        })
    return tuples


# ── Go harness builder ───────────────────────────────────────────────────

GO_HARNESS_DIR = REPO_ROOT / "experiments" / "phase_c_diff" / "go_harness"

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
	// Format: "Type::eid" (no outer quotes, no double-quotes around eid)
	idx := strings.Index(s, "::")
	if idx < 0 {
		return types.EntityUID{}, fmt.Errorf("bad UID: %q", s)
	}
	ty := types.EntityType(s[:idx])
	eid := types.String(s[idx+2:])
	return types.NewEntityUID(ty, eid), nil
}

func main() {
	// Read entities from arg[1] — JSON array of entity objects
	entitiesPath := os.Args[1]
	entitiesData, err := os.ReadFile(entitiesPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "entities read:", err)
		os.Exit(2)
	}

	// cedar-go EntityMap can be unmarshalled from the standard entities JSON format
	var entities types.EntityMap
	if err := json.Unmarshal(entitiesData, &entities); err != nil {
		// The file is a JSON array, not a map — need to build from slice.
		// Build entities manually from our fixed set.
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

		// PolicySet.IsAuthorized implements PolicyIterator interface
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
module kairos-cedar-diff/go-harness

go 1.24

require github.com/cedar-policy/cedar-go v0.0.0

replace github.com/cedar-policy/cedar-go => /work/cedar-go
"""


def build_go_harness() -> bool:
    """Write and build the Go stdin harness."""
    GO_HARNESS_DIR.mkdir(parents=True, exist_ok=True)
    (GO_HARNESS_DIR / "go.mod").write_text(GO_HARNESS_MOD)
    (GO_HARNESS_DIR / "main.go").write_text(GO_HARNESS_MAIN)

    proc = run_in_image(
        [
            "bash", "-c",
            "cd /work/experiments/phase_c_diff/go_harness && "
            "GOFLAGS='-mod=mod -buildvcs=false' go mod tidy >/dev/null 2>&1 && "
            "GOFLAGS='-mod=mod -buildvcs=false' go build -o /tmp/diff-harness . 2>&1",
        ],
        timeout=180,
    )
    if proc.returncode != 0:
        print("Go harness build failed:")
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])
        return False
    return True


# ── Rust cedar authorize ─────────────────────────────────────────────────

def run_rust_batch(
    tuples: list[dict[str, str]],
    schema_file: str,
    entities_file: str,
    timeout: int = 600,
) -> dict[str, str]:
    """Run cedar authorize for all tuples in a single container invocation.
    Writes a shell script that loops over tuples and emits TSV lines; parses results."""

    # Write the tuples as a JSONL file into the work tree
    rust_input_path = REPO_ROOT / "experiments" / "phase_c_diff" / "_rust_input.jsonl"
    with open(rust_input_path, "w") as f:
        for t in tuples:
            f.write(json.dumps(t) + "\n")

    # Shell script that reads the JSONL, writes per-tuple policy files, runs cedar authorize,
    # and emits TSV: idx TAB decision
    script = r"""
import json, subprocess, sys, os

input_path = "/work/experiments/phase_c_diff/_rust_input.jsonl"
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
    # Write the Python runner script into the work tree
    runner_path = REPO_ROOT / "experiments" / "phase_c_diff" / "_rust_runner.py"
    runner_path.write_text(script)

    proc = run_in_image(
        ["python3", "/work/experiments/phase_c_diff/_rust_runner.py",
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


# ── Go harness batch run ─────────────────────────────────────────────────

def run_go_batch(
    tuples: list[dict[str, str]],
    entities_file: str,
    timeout: int = 300,
) -> dict[str, str]:
    """Pipe all tuples as JSON to the Go harness stdin; parse JSON results."""
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

    # Write the payload to a temp location visible inside the container
    payload_host = REPO_ROOT / "experiments" / "phase_c_diff" / "_go_input.jsonl"
    payload_host.write_text(stdin_payload, encoding="utf-8")

    cmd = (
        "cd /work/experiments/phase_c_diff/go_harness && "
        "GOFLAGS='-mod=mod -buildvcs=false' go build -o /tmp/diff-harness . >/dev/null 2>&1 && "
        f"/tmp/diff-harness {entities_file} < /work/experiments/phase_c_diff/_go_input.jsonl"
    )
    proc = run_in_image(["bash", "-c", cmd], timeout=timeout)

    if proc.returncode != 0 and not proc.stdout.strip():
        print("Go harness run failed:")
        print(proc.stderr[-2000:])
        return {}

    results = {}
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


# ── Lean (cedar-spec) batch runner ───────────────────────────────────────
#
# Third oracle: cedar-spec's mechanised Lean evaluator. We re-use the same
# generator that produces the tuples (CedarFull.PolicyGen.genTuple), so the
# Lean evaluator gets the AST directly rather than re-parsing the text the
# Rust + Go runners see. Rationale: cedar-spec ships an evaluator over
# Cedar.Spec.Policy AST but no Lean text parser, and the Lean-side AST
# already IS the source of truth that gets serialized into the policy text
# the other two oracles parse. Letting Lean look up the canonical AST by
# idx is the fairest, most direct comparison.
#
# Wire shape: pipe the same TSV measure-diff emits (idx \t ... \t policy)
# into measure-lean's stdin. measure-lean only consumes `idx`, looks up
# `genTuple.val[i % supportSize]`, evaluates `Cedar.Spec.isAuthorized`
# against the same fixed entity store, emits `idx \t Allow|Deny`.

def run_lean_batch(
    tuples: list[dict[str, str]],
    timeout: int = 300,
) -> dict[str, str]:
    """Pipe idx-keyed tuple lines through measure-lean; parse decisions."""
    # Reconstruct the exact TSV measure-diff emits (Lean only needs idx,
    # but feeding the full line keeps the format symmetric and makes the
    # bridge resilient to future field re-ordering).
    lines = []
    for t in tuples:
        line = (
            f"{t['idx']}\t{t['principal']}\t{t['action']}\t"
            f"{t['resource']}\t{t['policy']}"
        )
        lines.append(line)
    payload = "\n".join(lines)

    payload_host = REPO_ROOT / "experiments" / "phase_c_diff" / "_lean_input.tsv"
    payload_host.write_text(payload, encoding="utf-8")

    cmd = (
        "cd /work/cedar-full && "
        ".lake/build/bin/measure-lean "
        "< /work/experiments/phase_c_diff/_lean_input.tsv"
    )
    proc = run_in_image(["bash", "-c", cmd], timeout=timeout)

    if proc.returncode != 0 and not proc.stdout.strip():
        print("Lean batch run failed:")
        print(proc.stderr[-2000:])
        return {}

    results: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        idx, decision = line.split("\t", 1)
        # measure-lean emits "Allow"/"Deny"/"ERROR:reason" — keep ERROR
        # prefix consistent with go/rust formats so downstream filtering
        # works uniformly.
        if decision.startswith("ERROR"):
            results[idx] = f"ERROR({decision[6:][:60]})"
        else:
            results[idx] = decision
    return results


def build_lean_oracle(timeout: int = 300) -> bool:
    """Lake-build measure-lean inside the container so the binary is ready."""
    proc = run_in_image(
        [
            "bash", "-c",
            "cd /work/cedar-full && lake build measure-lean 2>&1 | tail -5",
        ],
        timeout=timeout,
    )
    if proc.returncode != 0:
        print("Lean oracle build failed:")
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])
        return False
    return True


# ── Setup: write schema + entities files inside container space ──────────

def setup_fixtures() -> tuple[str, str]:
    """Write schema + entities to /work/experiments/phase_c_diff/fixtures/.
    Returns (schema_path, entities_path) as container-internal paths."""
    fixtures_dir = REPO_ROOT / "experiments" / "phase_c_diff" / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    schema_path = fixtures_dir / "schema.cedarschema"
    schema_path.write_text(FIXED_SCHEMA_TEXT)

    entities_path = fixtures_dir / "entities.json"
    entities_path.write_text(json.dumps(FIXED_ENTITIES, indent=2))

    container_schema = "/work/experiments/phase_c_diff/fixtures/schema.cedarschema"
    container_entities = "/work/experiments/phase_c_diff/fixtures/entities.json"
    return container_schema, container_entities


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="§8 diff runner: cedar-policy vs cedar-go")
    parser.add_argument("--n", type=int, default=1000, help="Number of tuples to sample")
    parser.add_argument(
        "--timeout", type=int, default=30,
        help="Per-tuple timeout for Rust cedar authorize (seconds)"
    )
    parser.add_argument(
        "--go-timeout", type=int, default=600,
        help="Total timeout for Go harness batch run (seconds)"
    )
    parser.add_argument(
        "--lean-timeout", type=int, default=600,
        help="Total timeout for Lean cedar-spec batch run (seconds)"
    )
    parser.add_argument("--skip-rust", action="store_true", help="Skip Rust authorize (faster)")
    parser.add_argument("--no-session", action="store_true",
                        help="Skip kairos.session wrapping (local-only, no Tahoe trace)")
    args = parser.parse_args()

    sink = ktrace.default_sink_from_env() if not args.no_session else None
    task_id = f"ath-529-cedar-full-n{args.n}-diff"
    session_cm = kairos.session(
        task_id=task_id,
        trace_sink=sink,
        vertical="auth",
        run_type="sdk_orchestration",
        run_subtype="differential_test",
        name_for_display=f"Cedar full-spec diff-run N={args.n}",
    )
    with session_cm as sess:
        sid = getattr(sess, "session_id", None) or getattr(sess, "task_id", task_id)
        print(f"[diff] session_id={sid} sink={type(sink).__name__}")
        return _run_diff(args, sess, sink)


def _run_diff(args, sess, sink) -> int:
    n = args.n
    print("=" * 72)
    print(f"  kairos-cedar §8 diff runner  N={n}")
    print(f"  image: {IMAGE}")
    print("=" * 72)

    t0_total = time.monotonic()
    _emit(sink, sess, "run_start", {
        "n_target": n,
        "image": IMAGE,
        "skip_rust": bool(args.skip_rust),
        "go_timeout": args.go_timeout,
        "rust_timeout": args.timeout,
    })

    # 1. Write fixtures
    print(f"\n[1/4] Writing fixed schema + entities fixtures ...")
    _emit(sink, sess, "phase_start", {"phase": "fixtures"})
    try:
        container_schema, container_entities = setup_fixtures()
    except Exception as e:
        _emit(sink, sess, "phase_error", {"phase": "fixtures", "error": str(e)})
        raise
    print(f"      schema  → {container_schema}")
    print(f"      entities→ {container_entities}")
    _emit(sink, sess, "phase_complete", {
        "phase": "fixtures",
        "schema_path": container_schema,
        "entities_path": container_entities,
        "schema_sha12": _sha12(FIXED_SCHEMA_TEXT),
    })

    # 2. Sample tuples from Lean generator
    print(f"\n[2/4] Sampling {n} tuples from CedarFull.PolicyGen ...")
    _emit(sink, sess, "phase_start", {"phase": "sample_tuples", "n_target": n})
    t_sample = time.monotonic()
    try:
        tuples = sample_tuples(n, timeout=300)
    except Exception as e:
        _emit(sink, sess, "phase_error", {"phase": "sample_tuples", "error": str(e)})
        raise
    elapsed_sample = time.monotonic() - t_sample
    if not tuples:
        _emit(sink, sess, "phase_error", {
            "phase": "sample_tuples", "error": "no tuples generated",
            "elapsed_sec": elapsed_sample,
        })
        _emit(sink, sess, "run_complete", {"status": "failed", "reason": "no_tuples"})
        print("FAIL: no tuples generated")
        return 1
    print(f"      Generated {len(tuples)} tuples in {elapsed_sample:.1f}s")
    if len(tuples) < n:
        print(f"      WARNING: only {len(tuples)}/{n} tuples parsed")
    _emit(sink, sess, "phase_complete", {
        "phase": "sample_tuples",
        "n_generated": len(tuples),
        "n_target": n,
        "elapsed_sec": elapsed_sample,
        "underflow": len(tuples) < n,
    })

    # 3. Build Go harness
    print(f"\n[3/4] Building Go diff harness ...")
    _emit(sink, sess, "phase_start", {"phase": "build_go_harness"})
    t_go = time.monotonic()
    go_ok = build_go_harness()
    if not go_ok:
        _emit(sink, sess, "phase_error", {"phase": "build_go_harness", "error": "build failed"})
        _emit(sink, sess, "run_complete", {"status": "failed", "reason": "go_harness_build_failed"})
        print("FAIL: Go harness build failed")
        return 1
    elapsed_go = time.monotonic() - t_go
    print(f"      Go harness built in {elapsed_go:.1f}s")
    _emit(sink, sess, "phase_complete", {
        "phase": "build_go_harness", "elapsed_sec": elapsed_go,
    })

    # 3.5. Build Lean oracle (cedar-spec evaluator)
    print(f"\n[3.5/4] Building Lean oracle (cedar-spec evaluator) ...")
    _emit(sink, sess, "phase_start", {"phase": "build_lean_oracle"})
    t_lean_build = time.monotonic()
    lean_ok = build_lean_oracle()
    if not lean_ok:
        _emit(sink, sess, "phase_error", {"phase": "build_lean_oracle", "error": "build failed"})
        _emit(sink, sess, "run_complete", {"status": "failed", "reason": "lean_oracle_build_failed"})
        print("FAIL: Lean oracle build failed")
        return 1
    elapsed_lean_build = time.monotonic() - t_lean_build
    print(f"      Lean oracle built in {elapsed_lean_build:.1f}s")
    _emit(sink, sess, "phase_complete", {
        "phase": "build_lean_oracle", "elapsed_sec": elapsed_lean_build,
    })

    # 4. Run diff: Go batch first (fast), Rust per-tuple, Lean batch
    print(f"\n[4/4] Running 3-way diff (Rust + Go + Lean) on {len(tuples)} tuples ...")

    # Go batch
    print(f"      [4a] Go batch ...")
    _emit(sink, sess, "phase_start", {"phase": "go_batch", "n_tuples": len(tuples)})
    t_go_run = time.monotonic()
    go_decisions = run_go_batch(tuples, container_entities, timeout=args.go_timeout)
    elapsed_go_run = time.monotonic() - t_go_run
    print(f"           {len(go_decisions)} decisions in {elapsed_go_run:.1f}s")
    _emit(sink, sess, "phase_complete", {
        "phase": "go_batch",
        "n_decisions": len(go_decisions),
        "n_tuples": len(tuples),
        "elapsed_sec": elapsed_go_run,
    })

    # Rust per-tuple (may be slow)
    rust_decisions: dict[str, str] = {}
    if not args.skip_rust:
        print(f"      [4b] Rust cedar authorize (per-tuple, may be slow) ...")
        _emit(sink, sess, "phase_start", {"phase": "rust_per_tuple", "n_tuples": len(tuples)})
        t_rust = time.monotonic()
        rust_decisions = run_rust_batch(
            tuples, container_schema, container_entities, timeout=args.timeout * len(tuples)
        )
        elapsed_rust = time.monotonic() - t_rust
        print(f"           {len(rust_decisions)} decisions in {elapsed_rust:.1f}s")
        _emit(sink, sess, "phase_complete", {
            "phase": "rust_per_tuple",
            "n_decisions": len(rust_decisions),
            "n_tuples": len(tuples),
            "elapsed_sec": elapsed_rust,
        })
    else:
        print(f"      [4b] Rust skipped (--skip-rust)")
        for t in tuples:
            rust_decisions[t["idx"]] = "skipped"

    # Lean batch (cedar-spec mechanised evaluator — third oracle for §8
    # triangulation). One container invocation, idx-keyed, AST-direct
    # (no text re-parse). Emits `Allow|Deny|ERROR:...` per tuple.
    print(f"      [4c] Lean cedar-spec batch (third oracle) ...")
    _emit(sink, sess, "phase_start", {"phase": "lean_per_tuple", "n_tuples": len(tuples)})
    t_lean_run = time.monotonic()
    lean_decisions = run_lean_batch(tuples, timeout=args.lean_timeout)
    elapsed_lean_run = time.monotonic() - t_lean_run
    print(f"           {len(lean_decisions)} decisions in {elapsed_lean_run:.1f}s")
    _emit(sink, sess, "phase_complete", {
        "phase": "lean_per_tuple",
        "n_decisions": len(lean_decisions),
        "n_tuples": len(tuples),
        "elapsed_sec": elapsed_lean_run,
    })

    # ── Summary ──────────────────────────────────────────────────────────

    total_elapsed = time.monotonic() - t0_total
    total = len(tuples)

    # Valid-sample rate: tuples where Go did NOT error
    go_valid = sum(1 for v in go_decisions.values() if not v.startswith("ERROR"))
    valid_rate = go_valid / total if total > 0 else 0.0

    # 3-way agreement: triangulation across (Rust, Go, Lean). Pairwise
    # disagreement counters surface which oracle pair drifted (e.g. Rust↔Go
    # = parser/text-format drift, Rust↔Lean or Go↔Lean = semantic drift,
    # all three disagreeing = generator-bug or fixture-mismatch).
    n_three_way_agreements = 0
    n_rust_go_disagreements = 0
    n_rust_lean_disagreements = 0
    n_go_lean_disagreements = 0
    n_any_pairwise_disagreement = 0
    disagreements: list[dict] = []
    compared = 0
    for t in tuples:
        idx = t["idx"]
        rd = rust_decisions.get(idx, "missing")
        gd = go_decisions.get(idx, "missing")
        ld = lean_decisions.get(idx, "missing")

        # Need all three to be real (non-error, non-skipped, non-missing)
        # for 3-way comparison. The pairwise rust-vs-go counter falls back
        # to skip-rust mode, but the 3-way and rust-lean / go-lean lanes
        # require Rust to be present.
        rd_ok = not rd.startswith("ERROR") and rd not in ("skipped", "missing")
        gd_ok = not gd.startswith("ERROR") and gd not in ("missing",)
        ld_ok = not ld.startswith("ERROR") and ld not in ("missing",)

        if not (rd_ok and gd_ok and ld_ok):
            continue

        compared += 1
        rg = (rd != gd)
        rl = (rd != ld)
        gl = (gd != ld)
        if rg:
            n_rust_go_disagreements += 1
        if rl:
            n_rust_lean_disagreements += 1
        if gl:
            n_go_lean_disagreements += 1
        if rg or rl or gl:
            n_any_pairwise_disagreement += 1
            disagreements.append({
                "idx": idx,
                "principal": t["principal"],
                "action": t["action"],
                "resource": t["resource"],
                "policy": t["policy"],
                "rust": rd,
                "go": gd,
                "lean": ld,
                "rust_go": rg,
                "rust_lean": rl,
                "go_lean": gl,
            })
        else:
            n_three_way_agreements += 1

    consensus_rate = n_three_way_agreements / compared if compared > 0 else float("nan")
    cost_per_tuple = total_elapsed / total if total > 0 else 0.0

    # Emit one differential_test_tuple event per compared triple. Schema
    # registry (qa PR #174 + Aidan 2026-04-24 generalisation) accepts the
    # base impl_a/impl_b fields; we extend with impl_c_* + three_way_consensus
    # via the model_config(extra="allow") slot. Per-tuple wall-clock is
    # amortised from batch totals (rust = elapsed_rust / N etc.) since the
    # runners batch invocations.
    rust_per = (elapsed_rust if not args.skip_rust else 0.0) / max(1, total)
    go_per = elapsed_go_run / max(1, total)
    lean_per = elapsed_lean_run / max(1, total)
    schema_hash = _sha12(FIXED_SCHEMA_TEXT)
    if sink is not None:
        for t in tuples:
            idx = t["idx"]
            rd = rust_decisions.get(idx, "missing")
            gd = go_decisions.get(idx, "missing")
            ld = lean_decisions.get(idx, "missing")
            if rd in ("skipped", "missing") or gd == "missing" or ld == "missing":
                continue
            request_blob = json.dumps({
                "principal": t["principal"],
                "action": t["action"],
                "resource": t["resource"],
            }, sort_keys=True)
            rd_ok = not rd.startswith("ERROR")
            gd_ok = not gd.startswith("ERROR")
            ld_ok = not ld.startswith("ERROR")
            three_way_consensus = (
                rd_ok and gd_ok and ld_ok and rd == gd == ld
            )
            # diff_found preserves the registry-defined pairwise A↔B semantics
            # (cedar-policy vs cedar-go) so existing dashboards don't break,
            # while impl_c_* + three_way_consensus carry the new triangulation
            # signal.
            diff_found_ab = (rd != gd) and rd_ok and gd_ok
            # Route through _emit so the per-tuple call uses TraceEvent
            # dataclass (not dict) — without this, SupabaseTraceSink.emit
            # silently fails with AttributeError on dict.run_subtype.
            _emit(sink, sess, "differential_test_tuple", {
                "sample_id": str(idx),
                "impl_a_name": "cedar-policy",
                "impl_a_verdict": rd,
                "impl_a_elapsed_sec": rust_per,
                "impl_b_name": "cedar-go",
                "impl_b_verdict": gd,
                "impl_b_elapsed_sec": go_per,
                "impl_c_name": "cedar-lean",
                "impl_c_verdict": ld,
                "impl_c_elapsed_sec": lean_per,
                "three_way_consensus": three_way_consensus,
                "diff_found": diff_found_ab,
                "input_hashes": {
                    "policy": _sha12(t["policy"]),
                    "schema": schema_hash,
                    "request": _sha12(request_blob),
                },
                "diff_details": (
                    f"rust={rd} go={gd} lean={ld} principal={t['principal']} "
                    f"action={t['action']} resource={t['resource']}"
                ) if not three_way_consensus else None,
            })

    print("\n" + "=" * 72)
    print("  §8 EVALUATION SUMMARY (3-way: Rust + Go + Lean)")
    print("=" * 72)
    print(f"  N sampled              : {total}")
    print(f"  Valid-sample rate      : {valid_rate:.3f}  ({go_valid}/{total} Go non-error)")
    print(f"  Triples compared       : {compared}  (all three oracles returned non-error)")
    print(f"  3-way consensus        : {n_three_way_agreements}/{compared} ({consensus_rate:.4f})")
    print(f"  Rust ↔ Go disagree     : {n_rust_go_disagreements}")
    print(f"  Rust ↔ Lean disagree   : {n_rust_lean_disagreements}")
    print(f"  Go   ↔ Lean disagree   : {n_go_lean_disagreements}")
    print(f"  Any-pairwise disagree  : {n_any_pairwise_disagreement}")
    print(f"  Wall-time total        : {total_elapsed:.1f}s")
    print(f"  Cost per tuple         : {cost_per_tuple:.3f}s")

    # Terminal run_complete event — closes the session in DB so it doesn't
    # get marked failed by the stale-run watchdog (ATH-571). This event +
    # the per-tuple differential_test_tuple events are what populate paper
    # §8 Table 4 and the new 3-way triangulation columns.
    # NaN isn't valid JSON — PostgREST rejects it with PGRST102. Stash as
    # None when compared=0 so the DB row is clean.
    import math as _math
    _consensus_rate = (None if _math.isnan(consensus_rate) else consensus_rate)
    _emit(sink, sess, "run_complete", {
        "status": "succeeded",
        "n_target": n,
        "n_sampled": total,
        "n_go_valid": go_valid,
        "valid_rate": valid_rate,
        "n_compared": compared,
        "n_three_way_agreements": n_three_way_agreements,
        "n_rust_go_disagreements": n_rust_go_disagreements,
        "n_rust_lean_disagreements": n_rust_lean_disagreements,
        "n_go_lean_disagreements": n_go_lean_disagreements,
        "any_pairwise_disagreement_count": n_any_pairwise_disagreement,
        "consensus_rate": _consensus_rate,
        "wall_time_total_sec": total_elapsed,
        "cost_per_tuple_sec": cost_per_tuple,
        "skip_rust": bool(args.skip_rust),
        "oracles": ["cedar-policy", "cedar-go", "cedar-lean"],
    })

    if disagreements:
        print(f"\n  First {min(5, len(disagreements))} disagreements:")
        for d in disagreements[:5]:
            tag = []
            if d["rust_go"]: tag.append("R↔G")
            if d["rust_lean"]: tag.append("R↔L")
            if d["go_lean"]: tag.append("G↔L")
            tag_str = ",".join(tag)
            print(f"    idx={d['idx']}  rust={d['rust']}  go={d['go']}  lean={d['lean']}  [{tag_str}]")
            print(f"      {d['principal']} / {d['action']} / {d['resource']}")
            print(f"      policy: {d['policy'][:80]}")

        # Write full disagreement corpus
        disagree_path = REPO_ROOT / "experiments" / "phase_c_diff" / "disagreements.jsonl"
        with open(disagree_path, "w") as f:
            for d in disagreements:
                f.write(json.dumps(d) + "\n")
        print(f"\n  Full disagreement corpus → {disagree_path}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
