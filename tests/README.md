# tests/

CI-gated regression tests for the kairos-cedar repository. Each file
documents the bug class it catches and the audit that surfaced the
latent issue.

## Paper-evidence gates (FMCAD 2026)

These three tests were filed in the 2026-04-25 paper-evidence audit
after `bug-hunt-2026-04-25` re-discovered three latent issues in the
diff-testing infrastructure that had shipped without a regression gate.
They run on every push to main and every PR via
`.github/workflows/self-quality.yml`.

### `test_support_size_matches_claim.py` (Bug A)

**Discovered**: 2026-04-25.
**Impact**: paper text claimed `N=10000` over the V1 generator while
the generator's true unique-tuple support was 675. `MeasureDiff.lean`
cycles `i % support_size` so the "10000 tuples" was actually
"675 tuples replayed 14.8 times". Nothing in the harness or CI was
asserting that the realised support matched the paper's claim.

**Mitigation**: every entry in `tests/generator_manifest.toml` declares
its expected support and claimed evaluation count. The test computes
the realised support via closed-form combinatorics derived from the
generator source (so Lean is not required in CI) and fails on drift.
When the paper's claimed `N` exceeds the realised support, the manifest
must set `paper_must_disclose_cycling = true`, which forces the paper
text to use "N evaluations over a support of S" rather than "N tuples".

**Update protocol**: when widening a generator (e.g. shipping V2 with a
larger support), update `tests/generator_manifest.toml` in the same
commit as the generator change. The test failure forces both moves to
land atomically.

### `test_version_pin_matches_paper.py` (Bug B)

**Discovered**: 2026-04-25.
**Impact**: paper docstring claimed `cedar-policy 4.3.1` while the
container actually shipped `cedar-policy 4.10.0`. The drift had been
live for an unknown duration with nothing to catch it. The paper had
been claiming results against a different binary than what was actually
run.

**Mitigation**: `tests/version_pin.toml` is the source of truth for
toolchain pins. The test exec's `cedar --version` (host or container),
reads the cedar-go submodule pin via `git ls-tree HEAD cedar-go`, and
extracts Lean / Go / Rust pins from `containers/Containerfile`. Any
drift between the pinned values and the live binaries fails the test.
When docker is unavailable on a CI runner, the test falls back to
checking the Containerfile text against the manifest (catches the
"Containerfile drifted from manifest" class even without a build).

**Update protocol**: bump `tests/version_pin.toml` and the relevant
paper docstrings in the same commit as the toolchain bump.

### `test_cedar_cli_rc_semantics.py` (Bug C)

**Discovered**: 2026-04-25 (re-discovered; original latency unknown).
**Impact**: `cedar authorize` returns `rc=2` for any `Deny` decision,
not only on parser/evaluator errors. The original
`experiments/phase_c_diff/run_diff.py` treated `rc != 0` as "ERROR"
which silently mis-classified every clean `Deny` as a parser failure
and corrupted the agreement-rate denominator.

**Mitigation**: `experiments/lib/cedar_cli.py` is the single
implementation of the cedar-CLI result mapping. It collapses the four
real outcomes to `{Allow, Deny, ParseError, EvalError}` and is called
by both `run_diff.py` (V1 generator) and (when present)
`run_widened.py` (bug-hunt shapes). The test exercises four pre-recorded
fixtures (covering rc=0 Allow, rc=2 Deny, rc=2 ParseError, rc=2
EvalError) and, when the cedar binary is on PATH, three live
end-to-end probes. A separate `HarnessUsesSharedParserTest` asserts
that the runner files import the shared parser (or document an
explicit opt-out comment) so a future refactor cannot silently re-
introduce the substring-match logic.

**Update protocol**: if the cedar CLI changes its rc semantics
upstream (e.g. a 5.x release flips Deny back to rc=0), update the
sentinel constants in `experiments/lib/cedar_cli.py` and the live test
will pass on the new release.

## Existing tests (pre-2026-04-25)

* `test_preflight.py`: unit + smoke tests for `scripts/preflight.py`,
  the local-environment health probe.
* `test_repo_hygiene.py`: scans tracked files for internal infra leaks
  (Linear ticket IDs, internal paths, internal agent handles, AI-slop
  phrasings, secret-shaped tokens).
* `integration/`: heavier integration tests that require the full
  kairos-cedar container.
