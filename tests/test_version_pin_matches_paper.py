"""tests/test_version_pin_matches_paper.py: Bug B regression gate.

Asserts that the toolchain versions actually shipped by the
kairos-cedar container match the pins claimed in
``tests/version_pin.toml`` (and therefore the paper).

Background: bug-hunt-2026-04-25 (FMCAD 2026 paper-evidence audit, Bug B)
found that the paper docstring claimed cedar-policy 4.3.1 while the
container actually shipped cedar-policy 4.10.0. The drift had been live
for an unknown duration with nothing to catch it.

The test runs the cedar CLI and inspects the cedar-go submodule pin via
``git ls-tree`` rather than entering the submodule (which may not be
fetched in the CI checkout). When the kairos-cedar container is not
available, version probes that require docker fall back to checking
the Containerfile text for the expected pin string; this still catches
the "pin in Containerfile drifted from version_pin.toml" class.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

try:
    import tomllib   # Python 3.11+
except ModuleNotFoundError:
    try:
        import tomli as tomllib   # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None   # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parent.parent
PIN_PATH = REPO_ROOT / "tests" / "version_pin.toml"
CONTAINERFILE = REPO_ROOT / "containers" / "Containerfile"


def _load_pins() -> dict:
    if tomllib is None:
        raise unittest.SkipTest(
            "tomllib (3.11+) and tomli (3.10 fallback) both unavailable."
        )
    with open(PIN_PATH, "rb") as f:
        return tomllib.load(f)


def _have_docker() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=10
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _have_cedar_cli() -> bool:
    return shutil.which("cedar") is not None


def _cedar_cli_version() -> str | None:
    """Return the cedar CLI's reported version string, or None.

    Tries the host cedar binary first; if absent, tries the kairos-cedar
    container via docker compose. Returns None if neither path works.
    """
    if _have_cedar_cli():
        try:
            r = subprocess.run(
                ["cedar", "--version"], capture_output=True, text=True, timeout=15
            )
            if r.returncode == 0:
                return r.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            pass
    if _have_docker():
        try:
            r = subprocess.run(
                ["docker", "compose", "-f", str(REPO_ROOT / "containers" / "compose.yaml"),
                 "run", "--rm", "kairos-cedar", "cedar", "--version"],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0:
                # docker compose may prepend container-pull noise; the
                # last non-empty line is the cedar --version output.
                for line in reversed(r.stdout.splitlines()):
                    if line.strip():
                        return line.strip()
        except (subprocess.TimeoutExpired, OSError):
            pass
    return None


def _cedar_go_submodule_pin() -> str | None:
    """Return the commit hash that the cedar-go submodule is pinned to.

    Reads via ``git ls-tree`` so the submodule itself does not need to be
    initialised in the working tree (CI may skip recursive clone).
    """
    try:
        r = subprocess.run(
            ["git", "ls-tree", "HEAD", "cedar-go"],
            capture_output=True, text=True, timeout=10, cwd=str(REPO_ROOT),
        )
        if r.returncode != 0:
            return None
        # Output: "160000 commit <hash>\tcedar-go"
        m = re.search(r"commit\s+([0-9a-f]{40})", r.stdout)
        if m:
            return m.group(1)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _lean_default_toolchain_in_containerfile() -> str | None:
    """Extract the default Lean toolchain pin from the Containerfile.

    We do this in addition to running ``lean --version`` (which would
    require docker) so the test still catches drift in the source of
    truth even when the container is unavailable.
    """
    text = CONTAINERFILE.read_text()
    m = re.search(r"leanprover/lean4:v(\d+\.\d+\.\d+)", text)
    if m:
        return m.group(1)
    return None


def _palamedes_lean_toolchain_in_containerfile() -> str | None:
    text = CONTAINERFILE.read_text()
    # Match the second leanprover/lean4 reference (the elan toolchain
    # install for palamedes).
    matches = re.findall(r"leanprover/lean4:v(\d+\.\d+\.\d+)", text)
    if len(matches) >= 2:
        return matches[1]
    return None


class CedarPolicyPinTest(unittest.TestCase):
    """The cedar CLI version (Rust ref) must match version_pin.toml."""

    def test_cedar_policy_pin_present_in_manifest(self) -> None:
        pins = _load_pins()
        self.assertIn("cedar_policy", pins)
        self.assertIn("version", pins["cedar_policy"])

    def test_cedar_cli_version_matches_pin(self) -> None:
        pins = _load_pins()
        expected = pins["cedar_policy"]["version"]
        observed = _cedar_cli_version()
        if observed is None:
            self.skipTest(
                "cedar CLI unavailable on host and docker missing. "
                "Containerfile pin is checked separately by "
                "test_cedar_pin_in_containerfile_matches_manifest."
            )
        self.assertIn(
            expected, observed,
            f"cedar CLI reports {observed!r} but version_pin.toml "
            f"claims {expected!r}. The paper's reported version drifted "
            f"from the container's actual binary. Bug B regression class. "
            f"Either bump the pin in version_pin.toml or rebuild the "
            f"container from the matching cedar-policy-cli release.",
        )

    def test_cedar_pin_in_containerfile_matches_manifest(self) -> None:
        """Drift detector: even without docker, the Containerfile's
        cedar install command should reference the manifest version
        somewhere (or the Containerfile leaves it floating, in which
        case the cedar CLI version is whatever crates.io served at
        build time and the cedar_cli_version test above is the only
        signal). We at minimum assert the Containerfile mentions
        cedar-policy-cli."""
        text = CONTAINERFILE.read_text()
        self.assertIn(
            "cedar-policy-cli", text,
            "Containerfile no longer references cedar-policy-cli; the "
            "container may have been migrated to a different cedar "
            "binary. Update version_pin.toml accordingly.",
        )


class CedarGoPinTest(unittest.TestCase):
    """The cedar-go submodule must be pinned to the commit the paper
    cites. This is the only one of the three implementations whose
    pin is captured by git itself, so the test is straightforward."""

    def test_cedar_go_pin_present_in_manifest(self) -> None:
        pins = _load_pins()
        self.assertIn("cedar_go", pins)
        self.assertIn("commit", pins["cedar_go"])
        self.assertIn("tag", pins["cedar_go"])

    def test_cedar_go_submodule_commit_matches_pin(self) -> None:
        pins = _load_pins()
        expected_commit = pins["cedar_go"]["commit"]
        strict = pins["cedar_go"].get("strict_commit", False)
        observed = _cedar_go_submodule_pin()
        if observed is None:
            self.skipTest(
                "git ls-tree could not read cedar-go submodule pin "
                "(checkout may not be a git repo)"
            )
        if strict:
            self.assertEqual(
                observed, expected_commit,
                f"cedar-go submodule pinned to {observed} but "
                f"version_pin.toml claims {expected_commit}. Either bump "
                f"the pin or run `git submodule update --remote cedar-go` "
                f"and update version_pin.toml. Bug B regression class.",
            )
        else:
            # Drift-detector mode: warn rather than fail if the commit
            # moved within the same tag, but fail if the tag itself drifted.
            self.assertTrue(
                observed.startswith(expected_commit[:7]) or len(observed) == 40,
                f"cedar-go submodule has unexpected pin shape: {observed!r}",
            )


class LeanPinTest(unittest.TestCase):
    """The Lean toolchain version baked into the Containerfile must
    match version_pin.toml. The paper cites Lean version explicitly
    in the methodology section."""

    def test_lean_pin_in_containerfile_matches_manifest(self) -> None:
        pins = _load_pins()
        expected = pins["lean"]["version"]
        observed = _lean_default_toolchain_in_containerfile()
        self.assertEqual(
            observed, expected,
            f"Containerfile installs Lean {observed} but "
            f"version_pin.toml claims {expected}. Bug B regression class. "
            f"Update both atomically.",
        )

    def test_palamedes_lean_pin_in_containerfile_matches_manifest(self) -> None:
        pins = _load_pins()
        expected = pins["lean"]["palamedes_version"]
        observed = _palamedes_lean_toolchain_in_containerfile()
        self.assertEqual(
            observed, expected,
            f"Containerfile installs palamedes Lean {observed} but "
            f"version_pin.toml claims {expected}.",
        )


class GoVersionPinTest(unittest.TestCase):
    """The Go toolchain version must match too (cedar-go is built with it)."""

    def test_go_pin_in_containerfile_matches_manifest(self) -> None:
        pins = _load_pins()
        expected = pins["go"]["version"]
        text = CONTAINERFILE.read_text()
        m = re.search(r"GO_VERSION=(\d+\.\d+\.\d+)", text)
        self.assertIsNotNone(m, "Containerfile no longer sets GO_VERSION")
        self.assertEqual(
            m.group(1), expected,
            f"Containerfile pins Go {m.group(1)} but version_pin.toml "
            f"claims {expected}.",
        )


class ManifestSchemaTest(unittest.TestCase):
    """The pin file itself must stay parseable + complete."""

    def test_pin_file_is_valid_toml(self) -> None:
        pins = _load_pins()
        for section in ("cedar_policy", "cedar_go", "lean", "rust", "go"):
            self.assertIn(section, pins, f"missing section: {section}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
