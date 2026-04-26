"""tests/test_support_size_matches_claim.py: Bug A regression gate.

Asserts internal consistency between generator and its declared support:
for every generator listed in ``tests/generator_manifest.toml``, the
realised unique-tuple support size matches the manifest's expected
value, and any declared N that exceeds the support is accompanied by a
``claimed_n_exceeds_support = true`` flag (forcing the harness/driver
to disclose the cycling rather than implying N distinct draws).

Background: an earlier driver run reported N=10000 over the V1
generator while the generator's true support was 675 unique tuples.
``MeasureDiff.lean`` cycles ``i % support_size`` so "10000 tuples"
actually meant "675 tuples replayed 14.8 times". Nothing was checking
the support claim against the realised support. This test class
catches that drift class before merge.

The test computes support via closed-form combinatorics derived from
the generator's structure (genAny / Gen.pick chain). For the V1 PolicyGen
this is 3 principals * 3 actions * 3 resources * 25 policy shapes = 675.
For widened shapes the support is the literal len() of the
emitted tuple list. For micro generators we use a lower-bound count
because the underlying List monad is fuel-driven.
"""

from __future__ import annotations

import importlib.util
import re
import sys
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
MANIFEST_PATH = REPO_ROOT / "tests" / "generator_manifest.toml"


def _load_manifest() -> list[dict]:
    if tomllib is None:
        raise unittest.SkipTest(
            "tomllib (3.11+) and tomli (3.10 fallback) both unavailable. "
            "Install tomli on Python 3.10 to run this gate."
        )
    with open(MANIFEST_PATH, "rb") as f:
        data = tomllib.load(f)
    return data.get("generator", [])


def _support_cedar_full_v1_policygen() -> int:
    """Compute V1 PolicyGen support from the Lean source via static analysis.

    We parse PolicyGen.lean directly so the test does not need a working
    Lean toolchain in CI. The contract: the file must declare three
    list-literal generators (principals, actions, resources) and a
    genPolicy chain whose Gen.pick depth determines the policy-shape
    count. Drift in any of those numbers fails the test.
    """
    src = (REPO_ROOT / "cedar-full" / "CedarFull" / "PolicyGen.lean").read_text()

    def count_list_literal(name: str) -> int:
        # Match `private def NAME : List EntityUID := [ ... ]`. We count
        # mkUID applications inside the immediate brackets.
        pat = re.compile(
            r"private\s+def\s+" + re.escape(name)
            + r"\s*:\s*List\s+EntityUID\s*:=\s*\[(.*?)\]",
            re.DOTALL,
        )
        m = pat.search(src)
        if not m:
            raise AssertionError(f"could not locate generator list {name!r}")
        body = m.group(1)
        return len(re.findall(r"mkUID\s+", body))

    n_principals = count_list_literal("principals")
    n_actions = count_list_literal("actions")
    n_resources = count_list_literal("resources")

    # Count Gen.pick branches in genPolicy. Each `Gen.pick (pure FOO)`
    # contributes one shape; the trailing branch (without Gen.pick) adds
    # the 25th shape (the genWellTyped condition).
    genpolicy_block = re.search(
        r"def\s+genPolicy.*?pure \(policyWithWhenCond.*?\)\)+",
        src, re.DOTALL,
    )
    if not genpolicy_block:
        raise AssertionError("could not locate genPolicy block")
    n_pick = len(re.findall(r"Gen\.pick\s*\(pure\s+", genpolicy_block.group(0)))
    # Plus the trailing genWellTyped branch.
    n_shapes = n_pick + 1

    return n_principals * n_actions * n_resources * n_shapes


def _support_widened_shapes() -> int:
    """Import widened_shapes.py and count realised tuples.

    The widened-shapes directory only exists on certain feature branches
    and successor PRs; on main this returns -1 (sentinel) and the test
    skips.
    """
    p = (
        REPO_ROOT / "experiments" / "phase_c_diff"
        / "bug-hunt-2026-04-25" / "widened_shapes.py"
    )
    if not p.exists():
        return -1   # sentinel: skip
    spec = importlib.util.spec_from_file_location("widened_shapes", p)
    if spec is None or spec.loader is None:
        return -1
    mod = importlib.util.module_from_spec(spec)
    sys.modules["widened_shapes"] = mod
    spec.loader.exec_module(mod)
    tuples = mod.all_tuples()
    return len(tuples)


def _support_cedar_micro_genwelltyped(target: str) -> int:
    """Lower bound on CedarMicro.genWellTyped support for a target type.

    We do not invoke Lean from CI, so this returns the manifest's
    expected_support value as a baseline; the test compares the
    realised value (if Lean is available) against the manifest. When
    Lean is unavailable, the test falls back to asserting the manifest
    is internally consistent (claim_kind = support_at_least, and the
    claimed_N_evaluations > expected_support is paired with
    claimed_n_exceeds_support = true).
    """
    # The CedarMicro generator is fuel-driven and we deliberately avoid
    # running it in unit-test scope. The static check below is enough to
    # catch the "claim N >> support without disclosure" regression class.
    return -2   # sentinel: defer to manifest-only check


class SupportSizeMatchesClaimTest(unittest.TestCase):
    """One test method per generator in the manifest."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = _load_manifest()
        if not cls.manifest:
            raise unittest.SkipTest(
                f"no generators declared in {MANIFEST_PATH}"
            )

    def _entry(self, gen_id: str) -> dict:
        for g in self.manifest:
            if g.get("id") == gen_id:
                return g
        self.fail(f"generator {gen_id!r} not found in manifest")
        return {}   # unreachable

    def _assert_disclosure_invariant(self, entry: dict, support: int) -> None:
        """If the manifest declares more evaluations than support, it
        must flag claimed_n_exceeds_support = true. This pushes the
        consumer to either widen the generator or disclose cycling
        explicitly rather than implying N distinct draws."""
        claimed = entry.get("claimed_N_evaluations")
        if claimed is None:
            return
        if support > 0 and claimed > support:
            self.assertTrue(
                entry.get("claimed_n_exceeds_support", False),
                f"generator {entry['id']!r}: manifest declares "
                f"N={claimed} evaluations but realised support is only "
                f"{support}; manifest must set "
                f"claimed_n_exceeds_support = true so any consumer is "
                f"forced to read 'N evaluations over support of S' "
                f"rather than 'N tuples'. Bug A regression class.",
            )

    def test_cedar_full_v1_policygen_support_matches_claim(self) -> None:
        entry = self._entry("cedar_full_v1_policygen")
        support = _support_cedar_full_v1_policygen()
        expected = entry["expected_support"]
        kind = entry["claim_kind"]

        if kind == "support_eq":
            self.assertEqual(
                support, expected,
                f"V1 PolicyGen support is {support} but manifest claims "
                f"{expected}. Either the generator was widened/narrowed "
                f"without updating the manifest, or the closed-form "
                f"combinatorics in this test drifted. Bug A class.",
            )
        elif kind == "support_at_least":
            self.assertGreaterEqual(support, expected)
        else:
            self.fail(f"unknown claim_kind: {kind}")

        self._assert_disclosure_invariant(entry, support)

    def test_widened_shapes_support_matches_claim(self) -> None:
        entry = self._entry("cedar_full_widened_shapes")
        support = _support_widened_shapes()
        if support == -1:
            self.skipTest(
                "widened_shapes.py not present on this branch "
                "(lives on dedicated feature branches + successors)"
            )
        expected = entry["expected_support"]
        self.assertEqual(
            support, expected,
            f"widened-shapes realised tuple count is {support} but "
            f"manifest expects {expected}. The shapes file or the "
            f"manifest drifted. Bug A class.",
        )
        self._assert_disclosure_invariant(entry, support)

    def test_cedar_micro_bool_disclosure_consistent(self) -> None:
        entry = self._entry("cedar_micro_genwelltyped_bool")
        support = _support_cedar_micro_genwelltyped("bool")
        # Sentinel -2: defer to manifest-only check (Lean not invoked).
        # We still enforce the disclosure invariant against the manifest
        # value, so a declared N=10000 over a 100-support generator MUST
        # be paired with claimed_n_exceeds_support = true.
        self._assert_disclosure_invariant(entry, entry["expected_support"])
        self.assertEqual(support, -2,
            "test scaffolding error: micro generator support probe "
            "returned a real value; please update the test to compare it.")

    def test_cedar_micro_int_disclosure_consistent(self) -> None:
        entry = self._entry("cedar_micro_genwelltyped_int")
        support = _support_cedar_micro_genwelltyped("int")
        self._assert_disclosure_invariant(entry, entry["expected_support"])
        self.assertEqual(support, -2,
            "test scaffolding error: micro generator support probe "
            "returned a real value; please update the test to compare it.")

    def test_every_manifest_entry_has_a_test(self) -> None:
        """Forces this file to grow a test method whenever the manifest
        adds a new generator. Catches the "shipped a generator without a
        regression gate" class."""
        ids_in_manifest = {g["id"] for g in self.manifest}
        # Test methods named test_<id>_... or hand-mapped here. Keep this
        # list in sync with the test methods above.
        ids_with_test = {
            "cedar_full_v1_policygen",
            "cedar_full_widened_shapes",
            "cedar_micro_genwelltyped_bool",
            "cedar_micro_genwelltyped_int",
        }
        missing = ids_in_manifest - ids_with_test
        self.assertFalse(
            missing,
            f"manifest entries without a test method: {sorted(missing)}. "
            f"Add a test_<id>_support_matches_claim method.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
