"""
experiments/phase_c_diff/lean_runner.py - Lean oracle wrapper.

Invokes the measure-lean binary built from cedar-full/MeasureLean.lean,
which evaluates each (request, policy) tuple through Cedar.Spec.isAuthorized
directly in Lean (no text serialization round-trip).

Integration pattern:
    from experiments.phase_c_diff.lean_runner import run_lean_batch
    lean_decisions = run_lean_batch(n_tuples, timeout=300)
    # lean_decisions: dict[idx_str -> "Allow"|"Deny"|"ERROR(...)"]

The Lean oracle evaluates the same genTuple support that measure-diff uses,
so lean_decisions[idx] is directly comparable with go_decisions[idx] and
rust_decisions[idx] from run_diff.py.

--three-way mode in run_diff.py wires all three runners and computes:
    - rust vs go agreement (existing)
    - lean vs rust agreement (new)
    - lean vs go agreement (new)
    - three-way agreement (all three match)

Invocation inside the kairos-cedar container:
    cd /work/cedar-full && .lake/build/bin/measure-lean <n>

If the binary is not yet built, the runner falls back to:
    cd /work/cedar-full && lake env lean --run MeasureLean.lean <n>
(slower but does not require a prior `lake build` step).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
IMAGE = os.environ.get("KAIROS_CEDAR_IMAGE", "ghcr.io/athanor-ai/kairos-cedar:latest")


def _run_in_image(
    cmd: list[str], *, workdir: str = "/work", timeout: int = 600
) -> subprocess.CompletedProcess[str]:
    """Run a command inside the kairos-cedar container with the repo mounted."""
    argv = [
        "docker", "run", "--rm",
        "-v", f"{REPO_ROOT}:/work",
        "-w", workdir,
        IMAGE,
        *cmd,
    ]
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def _lean_cmd(n: int) -> list[str]:
    """Return the shell command that runs measure-lean for n tuples.

    Prefers the pre-built binary (.lake/build/bin/measure-lean) if it exists;
    falls back to `lake env lean --run` which is slower but always works after
    `lake build` has run at least once for the library dependencies.
    """
    binary_check = (
        "if [ -x /work/cedar-full/.lake/build/bin/measure-lean ]; then "
        f"cd /work/cedar-full && .lake/build/bin/measure-lean {n}; "
        "else "
        f"cd /work/cedar-full && lake env lean --run MeasureLean.lean {n}; "
        "fi"
    )
    return ["bash", "-c", binary_check]


def run_lean_batch(n: int, timeout: int = 600) -> dict[str, str]:
    """Run measure-lean for n tuples; return idx -> "Allow"|"Deny"|"ERROR(...)".

    Each output line is a JSON object: {"idx": "N", "decision": "Allow|Deny"}.
    Lines that do not parse cleanly are reported as ERROR entries.
    """
    proc = _run_in_image(_lean_cmd(n), timeout=timeout)

    if proc.returncode != 0 and not proc.stdout.strip():
        snippet = (proc.stderr or "")[-500:]
        print(f"      Lean oracle run failed (rc={proc.returncode}):\n{snippet}",
              file=sys.stderr)
        return {}

    results: dict[str, str] = {}
    for raw in proc.stdout.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
            idx = str(obj["idx"])
            dec = obj.get("decision", "")
            if dec in ("Allow", "Deny"):
                results[idx] = dec
            else:
                results[idx] = f"ERROR(unexpected decision: {dec!r})"
        except (json.JSONDecodeError, KeyError) as exc:
            # Lines from Lean's IO.eprintln (error messages) arrive on stderr,
            # but guard here too.
            results[f"parse_error_{len(results)}"] = f"ERROR(json: {exc}: {raw[:60]})"

    return results


def build_lean_oracle(timeout: int = 600) -> bool:
    """Build the measure-lean binary inside the container.

    Returns True on success.  Only needed before the first run or after
    source changes; subsequent run_lean_batch calls reuse the binary.
    """
    proc = _run_in_image(
        ["bash", "-c",
         "cd /work/cedar-full && lake build measure-lean 2>&1"],
        timeout=timeout,
    )
    if proc.returncode != 0:
        print("Lean oracle build failed:", file=sys.stderr)
        print(proc.stdout[-2000:], file=sys.stderr)
        print(proc.stderr[-500:], file=sys.stderr)
        return False
    return True


if __name__ == "__main__":
    # Quick smoke-test: run 5 tuples and print decisions.
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    decisions = run_lean_batch(n, timeout=300)
    if not decisions:
        print("ERROR: no decisions returned", file=sys.stderr)
        sys.exit(1)
    for idx, dec in sorted(decisions.items(), key=lambda kv: int(kv[0])):
        print(f"  {idx}: {dec}")
