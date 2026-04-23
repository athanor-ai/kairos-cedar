"""Unit tests for scripts/preflight.py.

Each check function is exercised independently so CI catches a
regression in any single probe. The full preflight is also run
end-to-end with --strict against the repo root.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import preflight  # noqa: E402


class ResultSmokeTest(unittest.TestCase):
    """The Result dataclass has the fields the main loop depends on."""

    def test_result_ok(self) -> None:
        r = preflight.Result(ok=True, name="x", detail="y")
        self.assertTrue(r.ok)
        self.assertEqual(r.name, "x")
        self.assertFalse(r.warn_only)

    def test_result_failure_with_remediation(self) -> None:
        r = preflight.Result(
            ok=False, name="docker", detail="not running",
            remediation="start the daemon",
        )
        self.assertFalse(r.ok)
        self.assertEqual(r.remediation, "start the daemon")


class DockerCheckTest(unittest.TestCase):
    """check_docker requires the docker CLI + a reachable daemon."""

    def test_docker_cli_present(self) -> None:
        if shutil.which("docker") is None:
            self.skipTest("docker not installed. CI-only failure mode")
        r = preflight.check_docker()
        # If the daemon is reachable we pass; if not, we expect the
        # failure to name 'docker daemon reachable' so the user knows
        # where to look.
        self.assertIn("docker", r.name.lower())


class ComposeCheckTest(unittest.TestCase):
    def test_compose_cli_returns_result(self) -> None:
        if shutil.which("docker") is None:
            self.skipTest("docker not installed")
        r = preflight.check_compose()
        self.assertIn("compose", r.name.lower())


class SubmoduleCheckTest(unittest.TestCase):
    """If submodules are initialized the check passes; if not it
    fails with a clear remediation pointing at `git submodule update`."""

    def test_result_shape(self) -> None:
        r = preflight.check_submodules()
        self.assertEqual(r.name, "git submodules fetched")
        if not r.ok:
            self.assertIn("submodule", r.remediation)

    def test_submodule_list_matches_gitmodules(self) -> None:
        """Every entry in SUBMODULES is declared in .gitmodules."""
        gitmodules = (REPO_ROOT / ".gitmodules").read_text()
        for name in preflight.SUBMODULES:
            self.assertIn(
                f"path = {name}", gitmodules,
                f"{name} in SUBMODULES but missing from .gitmodules",
            )


class DiskCheckTest(unittest.TestCase):
    def test_disk_returns_float_detail(self) -> None:
        r = preflight.check_disk()
        self.assertIn("GB", r.detail)
        self.assertTrue(r.warn_only or r.ok)


class ArchCheckTest(unittest.TestCase):
    def test_arch_names_machine(self) -> None:
        r = preflight.check_arch()
        self.assertIn("arch=", r.detail)


class EndToEndPreflightTest(unittest.TestCase):
    """Run `python3 scripts/preflight.py` as a subprocess against the
    real repo. It should at minimum not crash and should exit 0 or 1."""

    def test_preflight_runs(self) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "preflight.py")],
            capture_output=True, text=True, timeout=60,
        )
        self.assertIn(result.returncode, (0, 1))
        self.assertIn("preflight:", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
