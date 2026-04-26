"""experiments/lib/cedar_cli.py: canonical cedar CLI result parser.

The Rust ``cedar`` CLI has a non-obvious exit-code convention: ``cedar
authorize`` returns ``rc=2`` on a ``Deny`` decision, not only on
parser/evaluator errors. Older versions of the Phase C diff harness
compared the stderr text via uppercase substring matching, which
papered over the issue but produced fragile results (Bug C
classification).

This module is the single source of truth for mapping a
``subprocess.run(["cedar", "authorize", ...])`` ``CompletedProcess``
into one of four outcomes:

  * ``Allow``      : cedar reports the request is allowed
  * ``Deny``       : cedar reports the request is denied (no parse/eval
                     error). rc may be 0 or 2 depending on cedar version
                     and flags; this function normalises.
  * ``ParseError`` : cedar could not parse the policy text. The diff
                     harnesses treat this as ``Deny`` for outcome-level
                     equivalence, but it is recorded separately so the
                     V1 generator's ``agreement_both_reject`` bucket can
                     be distinguished from a true semantic Deny.
  * ``EvalError``  : cedar parsed the policy but the evaluator raised
                     (e.g. a malformed extension-type literal such as
                     ``decimal("+0.0")``). Same outcome semantics as
                     ParseError, recorded separately.

Both run_diff.py (V1 generator) and run_widened.py (widened shapes)
should call ``parse_cedar_cli_result`` rather than re-implementing the
substring-match logic. ``tests/test_cedar_cli_rc_semantics.py`` asserts
the mapping by synthesising real Allow / Deny / parse-error policies
and feeding them through the live cedar CLI.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Literal

CedarOutcome = Literal["Allow", "Deny", "ParseError", "EvalError"]


@dataclass(frozen=True)
class CedarCLIResult:
    """Structured outcome of a single ``cedar authorize`` invocation."""

    outcome: CedarOutcome
    returncode: int
    # Tail of stdout/stderr for diagnostics. Bounded to keep memory + log
    # noise reasonable when batching thousands of calls.
    stdout_tail: str
    stderr_tail: str

    @property
    def decision_outcome(self) -> str:
        """Outcome collapsed to ``{Allow, Deny}`` for V1 diff agreement.

        The V1 generator only produces well-formed policies, so a parse
        error here is itself a bug-class signal (and historically was
        the root cause of two cedar-go decision-flips). Callers that
        want to keep the four-way mapping should use ``outcome``.
        """
        if self.outcome == "Allow":
            return "Allow"
        return "Deny"


def _tail(s: str, n: int = 400) -> str:
    if not s:
        return ""
    return s[-n:]


def parse_cedar_cli_result(
    proc: subprocess.CompletedProcess[str],
) -> CedarCLIResult:
    """Map a ``cedar authorize`` ``CompletedProcess`` to a structured outcome.

    Decision rules, applied in order:

      1. ``stderr`` contains a parser-error marker  →  ``ParseError``.
         Cedar surfaces parse errors as ``while parsing policy``-style
         messages on stderr regardless of the rc.
      2. ``stderr`` contains an evaluator-error marker  →  ``EvalError``.
         Cedar surfaces evaluator errors as ``error while evaluating``
         on stderr (e.g. extension-type literal failure).
      3. The combined stdout+stderr text contains the literal token
         ``ALLOW`` (case-insensitive) and no error markers  →  ``Allow``.
      4. Otherwise treat as ``Deny``. This covers both ``rc=0`` clean
         denies and the more common ``rc=2`` deny path that older
         versions of the harness mis-classified as "ERROR".

    The function is intentionally conservative: it never returns
    ``Allow`` if ``stderr`` carries any error marker, even if the word
    "ALLOW" appears elsewhere in the output (e.g. the policy id).
    """
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    combined_lower = (stdout + "\n" + stderr).lower()

    # Parser-error markers. Cedar text varies a little across versions
    # (4.3.1 vs 4.10.0); these substrings cover both.
    parser_markers = (
        "while parsing policy",
        "failed to parse policy",
        "parse error",
        "syntax error",
    )
    if any(m in combined_lower for m in parser_markers):
        return CedarCLIResult(
            outcome="ParseError",
            returncode=proc.returncode,
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
        )

    # Evaluator-error markers, e.g. decimal("+0.0") and
    # ip("fe80::1%eth0") literals.
    eval_markers = (
        "error while evaluating",
        "extension function",
        "is not a well-formed",
        "invalid ip address",
    )
    if any(m in combined_lower for m in eval_markers):
        return CedarCLIResult(
            outcome="EvalError",
            returncode=proc.returncode,
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
        )

    # Decision tokens. cedar prints "ALLOW" or "DENY" (caps) on stdout
    # for the human-readable summary; the JSON form ("decision":
    # "Allow") also passes the case-insensitive check.
    if "allow" in combined_lower:
        return CedarCLIResult(
            outcome="Allow",
            returncode=proc.returncode,
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
        )

    # Default: treat as Deny. Historical harness mis-classified rc=2
    # Denies as ERROR; this branch is the fix.
    return CedarCLIResult(
        outcome="Deny",
        returncode=proc.returncode,
        stdout_tail=_tail(stdout),
        stderr_tail=_tail(stderr),
    )


# Sentinel rc values asserted by tests/test_cedar_cli_rc_semantics.py.
# These are documented at:
#   https://github.com/cedar-policy/cedar/blob/main/cedar-policy-cli/src/lib.rs
# but we keep an in-tree copy so the test invariant is auditable from
# the kairos-cedar checkout alone.
CEDAR_RC_ALLOW = 0
CEDAR_RC_DENY = 2
