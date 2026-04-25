"""tests/test_cedar_cli_rc_semantics.py: Bug C regression gate.

Asserts that ``experiments.lib.cedar_cli.parse_cedar_cli_result`` maps
real ``cedar authorize`` ``CompletedProcess`` outputs to the correct
``{Allow, Deny, ParseError, EvalError}`` outcome.

Background: bug-hunt-2026-04-25 (FMCAD 2026 paper-evidence audit, Bug C)
re-discovered that ``cedar authorize`` returns ``rc=2`` for any
``Deny`` decision, *not only* on parser/evaluator errors. The original
``experiments/phase_c_diff/run_diff.py`` treated ``rc=2`` as "ERROR"
which silently mis-classified every clean ``Deny`` as a parser failure
and corrupted the agreement-rate denominator. This test exercises the
actual cedar CLI behaviour with three minimal synthetic policies plus
two pre-recorded ``CompletedProcess`` fixtures (so the assertion holds
even when the cedar binary is not on PATH).

The pre-recorded fixtures are captured from real cedar 4.10.0 stderr
text. If cedar's stderr format changes upstream the test will fail,
which is the correct signal because both ``run_diff.py`` and
``run_widened.py`` will then be silently mis-classifying outputs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from experiments.lib.cedar_cli import (   # noqa: E402
    CEDAR_RC_ALLOW,
    CEDAR_RC_DENY,
    CedarCLIResult,
    parse_cedar_cli_result,
)


# ---------------------------------------------------------------
# Fixtures: real cedar 4.10.0 outputs captured from the kairos-cedar
# container during bug-hunt-2026-04-25. We re-record these whenever
# cedar's text format changes upstream.
# ---------------------------------------------------------------

# An ``Allow`` decision: cedar prints "ALLOW" on stdout and rc=0.
ALLOW_PROC = subprocess.CompletedProcess(
    args=["cedar", "authorize"],
    returncode=CEDAR_RC_ALLOW,
    stdout="ALLOW\n",
    stderr="",
)

# A clean ``Deny`` decision: cedar prints "DENY" on stdout and rc=2.
# This is the failure mode that bit run_diff.py: rc != 0 was read as
# "error" and the whole tuple was bucketed as ERROR.
DENY_PROC = subprocess.CompletedProcess(
    args=["cedar", "authorize"],
    returncode=CEDAR_RC_DENY,
    stdout="DENY\n",
    stderr="",
)

# A parse error: cedar prints "ERROR" plus a "while parsing policy"
# trace on stderr. rc varies; we capture rc=2.
PARSE_ERROR_PROC = subprocess.CompletedProcess(
    args=["cedar", "authorize"],
    returncode=CEDAR_RC_DENY,
    stdout="",
    stderr=(
        "Error: failed to parse policy\n"
        "  ./policy.cedar:1:8\n"
        "    1 | permit(\n"
        "  unexpected token, while parsing policy\n"
    ),
)

# An evaluator error: cedar prints "DENY" on stdout *and* a
# "error while evaluating" trace on stderr. The bug-hunt classification
# distinguishes EvalError from a clean Deny because the cedar-go bug
# class lives in this bucket (decimal("+0.0"), ip("fe80::1%eth0")).
EVAL_ERROR_PROC = subprocess.CompletedProcess(
    args=["cedar", "authorize"],
    returncode=CEDAR_RC_DENY,
    stdout="DENY\n",
    stderr=(
        "error while evaluating policy `policy0`: "
        "error while evaluating `decimal` extension function: "
        "`+0.0` is not a well-formed decimal value\n"
    ),
)


class FixtureMappingTest(unittest.TestCase):
    """The four pre-recorded fixtures map to the four expected outcomes."""

    def test_allow_fixture(self) -> None:
        r = parse_cedar_cli_result(ALLOW_PROC)
        self.assertIsInstance(r, CedarCLIResult)
        self.assertEqual(r.outcome, "Allow")
        self.assertEqual(r.returncode, CEDAR_RC_ALLOW)
        self.assertEqual(r.decision_outcome, "Allow")

    def test_deny_fixture_with_rc_2_is_not_misclassified_as_error(self) -> None:
        """The Bug C regression test. rc=2 with a clean DENY stdout must
        be classified as Deny, not ERROR."""
        r = parse_cedar_cli_result(DENY_PROC)
        self.assertEqual(
            r.outcome, "Deny",
            f"rc=2 with stdout='DENY' was classified as {r.outcome!r}, "
            f"reproducing Bug C from bug-hunt-2026-04-25. "
            f"parse_cedar_cli_result must treat rc=2 as a Deny path, "
            f"not an error path.",
        )
        self.assertEqual(r.returncode, CEDAR_RC_DENY)
        self.assertEqual(r.decision_outcome, "Deny")

    def test_parse_error_fixture(self) -> None:
        r = parse_cedar_cli_result(PARSE_ERROR_PROC)
        self.assertEqual(r.outcome, "ParseError")
        self.assertEqual(r.decision_outcome, "Deny",
            "Outcome-level: a parse error counts as Deny for V1 diff "
            "agreement (the V1 agreement_both_reject bucket).")

    def test_eval_error_fixture(self) -> None:
        r = parse_cedar_cli_result(EVAL_ERROR_PROC)
        self.assertEqual(
            r.outcome, "EvalError",
            "An eval error must NOT be classified as a clean Deny: "
            "the bug-hunt-2026-04-25 cedar-go bug class lives in the "
            "EvalError bucket (decimal+0.0, ip fe80::1%%eth0).",
        )
        self.assertEqual(r.decision_outcome, "Deny")


class StdoutDoesNotPolluteAllowTest(unittest.TestCase):
    """Regression: the original substring-match harness would have
    classified ``decimal_allow_policy`` as Allow because the policy id
    contains the literal "allow" token. Our parser must not."""

    def test_eval_error_with_allow_in_policy_id_is_eval_error(self) -> None:
        proc = subprocess.CompletedProcess(
            args=["cedar", "authorize"],
            returncode=CEDAR_RC_DENY,
            stdout="DENY\n",
            stderr=(
                "error while evaluating policy `permit_allow_admin`: "
                "error while evaluating `ipaddr` extension function: "
                "invalid IP address: fe80::1%eth0\n"
            ),
        )
        r = parse_cedar_cli_result(proc)
        self.assertEqual(r.outcome, "EvalError")


# ---------------------------------------------------------------
# Live cedar CLI tests. Run only when cedar is on PATH (the kairos-cedar
# container has it). These tests synthesize three minimal policies and
# assert the actual cedar binary's output matches the parser.
# ---------------------------------------------------------------


def _have_cedar() -> bool:
    return shutil.which("cedar") is not None


_ALLOW_POLICY = """\
permit(principal, action, resource);
"""

_DENY_POLICY = """\
forbid(principal, action, resource);
"""

# Syntax error: missing closing paren and semicolon.
_PARSE_ERROR_POLICY = """\
permit(principal, action, resource
"""

_FIXED_SCHEMA = """\
entity User;
entity Document;
action view appliesTo {
    principal: User,
    resource: [Document],
};
"""

_FIXED_ENTITIES = """\
[
  {"uid": {"type": "User", "id": "alice"}, "attrs": {}, "parents": []},
  {"uid": {"type": "Document", "id": "doc1"}, "attrs": {}, "parents": []}
]
"""


def _run_cedar_authorize(
    policy_text: str, schema_path: Path, entities_path: Path,
    workdir: Path,
) -> subprocess.CompletedProcess[str]:
    pol_path = workdir / "policy.cedar"
    pol_path.write_text(policy_text)
    cmd = [
        "cedar", "authorize",
        "--policies", str(pol_path),
        "--entities", str(entities_path),
        "--schema", str(schema_path),
        "--request-validation", "false",
        "--principal", 'User::"alice"',
        "--action", 'Action::"view"',
        "--resource", 'Document::"doc1"',
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


@unittest.skipUnless(_have_cedar(), "cedar CLI not on PATH")
class LiveCedarCLITest(unittest.TestCase):
    """Exercises the real cedar binary so the parser stays in sync with
    upstream stderr formatting. Skipped on hosts without the cedar CLI;
    the kairos-cedar CI workflow installs it explicitly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.workdir = Path(cls._tmp.name)
        cls.schema_path = cls.workdir / "schema.cedarschema"
        cls.schema_path.write_text(_FIXED_SCHEMA)
        cls.entities_path = cls.workdir / "entities.json"
        cls.entities_path.write_text(_FIXED_ENTITIES)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_live_allow(self) -> None:
        proc = _run_cedar_authorize(
            _ALLOW_POLICY, self.schema_path, self.entities_path, self.workdir,
        )
        r = parse_cedar_cli_result(proc)
        self.assertEqual(r.outcome, "Allow",
            f"live cedar Allow misclassified. rc={proc.returncode} "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertEqual(proc.returncode, CEDAR_RC_ALLOW)

    def test_live_deny(self) -> None:
        proc = _run_cedar_authorize(
            _DENY_POLICY, self.schema_path, self.entities_path, self.workdir,
        )
        r = parse_cedar_cli_result(proc)
        self.assertEqual(r.outcome, "Deny",
            f"live cedar Deny misclassified. rc={proc.returncode} "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}. "
            f"This is the Bug C regression: rc=2 must map to Deny.")
        # The Bug C invariant: rc must be the documented Deny rc, not 0.
        self.assertEqual(
            proc.returncode, CEDAR_RC_DENY,
            f"cedar CLI rc semantics changed upstream: a clean Deny "
            f"now returns rc={proc.returncode} (was rc=2 in 4.10.0). "
            f"Update CEDAR_RC_DENY in experiments/lib/cedar_cli.py and "
            f"the parser if cedar's rc convention has shifted.",
        )

    def test_live_parse_error(self) -> None:
        proc = _run_cedar_authorize(
            _PARSE_ERROR_POLICY, self.schema_path, self.entities_path, self.workdir,
        )
        r = parse_cedar_cli_result(proc)
        self.assertEqual(r.outcome, "ParseError",
            f"live cedar parse-error misclassified. rc={proc.returncode} "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}")


class HarnessUsesSharedParserTest(unittest.TestCase):
    """Forces both diff harnesses to call ``parse_cedar_cli_result``
    rather than re-implementing rc / stderr parsing inline. If a future
    refactor inlines the substring-match logic again, this test fails.

    The check is conservative: we look for telltale inline patterns in
    the runner sources and require either the import line or an explicit
    opt-out comment. The opt-out is intentionally awkward so the
    refactor decision is visible in code review."""

    def _read(self, rel: str) -> str | None:
        p = REPO_ROOT / rel
        return p.read_text() if p.exists() else None

    def test_phase_c_run_diff_either_imports_or_opts_out(self) -> None:
        text = self._read("experiments/phase_c_diff/run_diff.py")
        if text is None:
            self.skipTest("run_diff.py not present on this branch")
        imports_lib = (
            "from experiments.lib.cedar_cli" in text
            or "experiments.lib.cedar_cli" in text
        )
        explicit_optout = "# CEDAR_CLI_PARSER_OPT_OUT" in text
        self.assertTrue(
            imports_lib or explicit_optout,
            "experiments/phase_c_diff/run_diff.py does not import the "
            "shared cedar_cli.parse_cedar_cli_result helper. Either "
            "import it or add a CEDAR_CLI_PARSER_OPT_OUT comment "
            "documenting why this harness re-implements the rc/stderr "
            "mapping inline. Bug C regression class.",
        )

    def test_widened_run_widened_either_imports_or_opts_out(self) -> None:
        text = self._read(
            "experiments/phase_c_diff/bug-hunt-2026-04-25/run_widened.py"
        )
        if text is None:
            self.skipTest("run_widened.py not present on this branch")
        imports_lib = (
            "from experiments.lib.cedar_cli" in text
            or "experiments.lib.cedar_cli" in text
        )
        explicit_optout = "# CEDAR_CLI_PARSER_OPT_OUT" in text
        self.assertTrue(
            imports_lib or explicit_optout,
            "run_widened.py does not import the shared cedar_cli helper. "
            "Same Bug C regression class as the V1 harness.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
