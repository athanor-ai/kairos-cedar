"""Repo-hygiene tests — catch accidental leaks of internal infra into
the public kairos-cedar tree.

If someone pastes a Linear ticket ID, a Slack user ID, an internal
agent handle, a kairos SDK internal symbol, or an internal path into
a tracked file, this test fails.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files and directories we never scan (upstream submodules + lake caches
# may legitimately mention some of these tokens in their own context).
EXCLUDE_DIRS = {
    ".git",
    ".lake",
    "cedar-spec",
    "palamedes-lean",
    "cedar-go",
    "cedar-integration-tests",
}

# Extensions we scan (binaries + images ignored).
SCAN_EXTS = {
    ".md", ".py", ".sh", ".yaml", ".yml", ".toml",
    ".lean", ".Containerfile", ".txt", ".json",
}

# Patterns that must NEVER appear in the public repo. Add to this
# aggressively if we ship more public work — the cost of a false
# positive is a one-line rename; the cost of a false negative is an
# internal handle sitting on github.com.
FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    # Linear ticket IDs
    (r"\bATH-\d+\b", "internal Linear ticket id"),
    # Slack user IDs (anything that looks like <@U0AS...> or bare U0AS...)
    (r"U0A[SR][A-Z0-9]{8,}", "internal Slack user id"),
    # Internal agent identities in mention form
    (r"@(platform|qa|asabi|research|cto|orchestrator)\b", "internal agent handle"),
    # Internal paths
    (r"/home/(azureuser|aidayang)/", "internal absolute path"),
    # Secret-shaped tokens
    (r"xoxb-[A-Za-z0-9-]+", "Slack bot token"),
    (r"ghp_[A-Za-z0-9]{30,}", "GitHub personal token"),
    (r"\bsk-[A-Za-z0-9]{20,}", "OpenAI/Anthropic api key"),
    # Closed-source kairos SDK internal surfaces — we don't list these
    # in public docs. Mentions of "kairos" as a general name are fine;
    # internal symbols are not.
    (r"kairos\.(spec|verticals|trace|solve)\b", "closed-source kairos SDK internal"),
    (r"\b(SpecPipeline|OpusOrchestrator|VerifierPlugin)\b", "closed-source SDK type"),
    # Infra references
    (r"\b(tahoe|vercel)\.athanor", "internal infra reference"),
    (r"SUPABASE_SERVICE_ROLE_KEY|ATHANOR_CRON_SECRET|ATHANOR_SYNC_TOKEN", "infra secret env var"),
    # Memory / agent-msg internals
    (r"feedback_[a-z_]+\.md", "internal agent memory filename"),
    (r"\bagent-msg\b", "internal fleet-coordination CLI"),
    # Linear-footer convention
    (r"_Filed by: @", "internal Linear authorship footer"),
]


def _scan_paths() -> list[Path]:
    """Every tracked file under scannable extensions, skipping excludes."""
    out: list[Path] = []
    for p in REPO_ROOT.rglob("*"):
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        if not p.is_file():
            continue
        if p.suffix not in SCAN_EXTS:
            continue
        out.append(p)
    return out


class NoInternalLeaksTest(unittest.TestCase):
    def test_no_forbidden_patterns(self) -> None:
        violations: list[str] = []
        paths = _scan_paths()
        for path in paths:
            text = path.read_text(errors="replace")
            # Also skip this test file itself — it necessarily contains
            # the patterns it's asserting about.
            if path.name == "test_repo_hygiene.py":
                continue
            for pattern, label in FORBIDDEN_PATTERNS:
                for m in re.finditer(pattern, text):
                    rel = path.relative_to(REPO_ROOT)
                    violations.append(f"{rel}: {label}: {m.group(0)!r}")

        if violations:
            self.fail(
                "Internal-leak patterns detected in tracked files:\n"
                + "\n".join(f"  - {v}" for v in violations[:30])
                + (f"\n  ... and {len(violations) - 30} more" if len(violations) > 30 else "")
            )

    def test_scan_covered_at_least_10_files(self) -> None:
        """Sanity: we're actually scanning something — not a no-op."""
        paths = _scan_paths()
        self.assertGreaterEqual(
            len(paths), 10,
            f"scan only found {len(paths)} files — EXCLUDE_DIRS may be too aggressive",
        )


class NoHostnamesInLockfilesTest(unittest.TestCase):
    """Lake manifest should not reference local paths from our dev VM."""

    def test_bridge_lake_manifest_clean(self) -> None:
        manifest = REPO_ROOT / "cedar-spec-bridge" / "lake-manifest.json"
        if not manifest.exists():
            self.skipTest("lake-manifest.json not yet generated (lake update hasn't run)")
        text = manifest.read_text()
        self.assertNotIn("/home/", text)
        self.assertNotIn("azureuser", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
