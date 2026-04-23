#!/usr/bin/env python3
"""preflight.py — verify everything is in place before you build images.

Checks:
  1. docker daemon is running + reachable.
  2. docker compose subcommand works (Compose V2, not legacy docker-compose).
  3. git submodules fetched (cedar-spec, palamedes-lean, cedar-go,
     cedar-integration-tests).
  4. Enough disk space (images total ~15 GB; we check for 30 GB free).
  5. Host architecture is x86_64 (Verus binary + Lean toolchains are x86 pinned).

Exits 0 if every check passes; nonzero on first failure and prints
the remediation.

Usage:
    python3 scripts/preflight.py
    python3 scripts/preflight.py --strict   # warnings also fail
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SUBMODULES = ("cedar-spec", "palamedes-lean", "cedar-go", "cedar-integration-tests")
MIN_FREE_GB = 30


@dataclass
class Result:
    ok: bool
    name: str
    detail: str = ""
    remediation: str = ""
    warn_only: bool = False


def check_docker() -> Result:
    if shutil.which("docker") is None:
        return Result(
            ok=False, name="docker installed",
            detail="`docker` not on PATH",
            remediation="Install Docker Engine or Desktop — https://docs.docker.com/get-docker/",
        )
    try:
        proc = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Result(
            ok=False, name="docker daemon reachable",
            detail=f"`docker info` failed: {type(exc).__name__}: {exc}",
            remediation="Start the Docker daemon (`sudo systemctl start docker` on Linux, or open Docker Desktop).",
        )
    if proc.returncode != 0:
        return Result(
            ok=False, name="docker daemon reachable",
            detail=f"`docker info` exit {proc.returncode}: {proc.stderr.strip()[:200]}",
            remediation="Ensure your user is in the `docker` group (Linux): `sudo usermod -aG docker $USER && newgrp docker`.",
        )
    return Result(ok=True, name="docker daemon reachable", detail="`docker info` OK")


def check_compose() -> Result:
    try:
        proc = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Result(
            ok=False, name="docker compose available",
            detail=f"`docker compose version` failed: {exc}",
            remediation="Upgrade to Docker Engine 20.10+ which bundles Compose V2.",
        )
    if proc.returncode != 0:
        return Result(
            ok=False, name="docker compose available",
            detail=f"`docker compose version` exit {proc.returncode}",
            remediation="Install Compose V2 (the `docker compose` subcommand, not the legacy `docker-compose` binary).",
        )
    return Result(
        ok=True, name="docker compose available",
        detail=proc.stdout.strip(),
    )


def check_submodules() -> Result:
    missing = []
    for name in SUBMODULES:
        path = REPO_ROOT / name
        if not path.exists() or not any(path.iterdir()):
            missing.append(name)
    if missing:
        return Result(
            ok=False, name="git submodules fetched",
            detail=f"empty or missing: {', '.join(missing)}",
            remediation="Run `git submodule update --init --recursive` from the repo root.",
        )
    return Result(
        ok=True, name="git submodules fetched",
        detail=f"all {len(SUBMODULES)} present",
    )


def check_disk() -> Result:
    stats = shutil.disk_usage(REPO_ROOT)
    free_gb = stats.free / (1024**3)
    if free_gb < MIN_FREE_GB:
        return Result(
            ok=False, name="disk space",
            detail=f"{free_gb:.1f} GB free (need ≥ {MIN_FREE_GB} GB for all three images)",
            remediation=f"Free ~{MIN_FREE_GB - free_gb:.0f} GB. Images total ~15 GB; builds + scratch need ~2x that.",
            warn_only=True,
        )
    return Result(
        ok=True, name="disk space",
        detail=f"{free_gb:.1f} GB free",
    )


def check_arch() -> Result:
    machine = platform.machine()
    if machine not in ("x86_64", "AMD64"):
        return Result(
            ok=False, name="host architecture",
            detail=f"arch={machine} (Verus + Lean toolchains are x86_64-pinned in this repo)",
            remediation="Use an x86_64 Linux host (or an x86_64 VM on Apple Silicon). ARM builds are not supported by the Verus binary release.",
            warn_only=True,
        )
    return Result(ok=True, name="host architecture", detail=f"arch={machine}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight cedar-diff-fleet")
    parser.add_argument(
        "--strict", action="store_true",
        help="Treat warn-only failures (disk, arch) as fatal.",
    )
    args = parser.parse_args()

    checks = [check_docker, check_compose, check_submodules, check_disk, check_arch]
    results = [fn() for fn in checks]

    had_fatal = False
    had_warn = False
    for r in results:
        if r.ok:
            print(f"  [ok]   {r.name}  —  {r.detail}")
        else:
            tag = "warn" if r.warn_only else "FAIL"
            print(f"  [{tag}] {r.name}")
            print(f"         → {r.detail}")
            print(f"         fix: {r.remediation}")
            if r.warn_only:
                had_warn = True
                if args.strict:
                    had_fatal = True
            else:
                had_fatal = True

    print()
    if had_fatal:
        print("preflight: failed. Fix the [FAIL] items above, then re-run.")
        return 1
    if had_warn and not args.strict:
        print("preflight: passed with warnings. Re-run with --strict if you want them gated.")
    else:
        print("preflight: all green. Build images with:")
        print("  docker compose -f containers/compose.yaml build spec rust-verus")
        print("  # palamedes is optional + heavy (~9.5 GB, ~15 min); skip unless on the V3 track:")
        print("  docker compose -f containers/compose.yaml build palamedes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
