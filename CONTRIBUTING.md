# Contributing to kairos-cedar

Thanks for your interest. kairos-cedar is the type-directed
differential-testing workbench for Cedar policy languages, built on top
of the mechanised Lean specification. Every PR should make the next
soundness claim faster to ship or stronger to defend.

By participating, you agree to abide by the
[Code of Conduct](CODE_OF_CONDUCT.md).

## What kairos-cedar is, and is not

**kairos-cedar is** an Apache-2.0 Lean 4 + Cedar artefact repo:
- A type-directed generator for Cedar policies, derived from
  [`cedar-spec`](https://github.com/cedar-policy/cedar-spec)'s
  mechanised type-checker via program synthesis (per the
  [Palamedes](https://github.com/hgoldstein95/palamedes-lean)
  pattern, ICFP 2025).
- A differential-testing harness running each generated policy against
  the [Rust reference](https://github.com/cedar-policy/cedar) +
  [Go reimplementation](https://github.com/cedar-policy/cedar-go),
  reporting agreement / disagreement / asymmetric-path counts.
- Three Lake projects: `cedar-spec-bridge` (`Prop`-wrapper around
  `Cedar.Validation.typeOf`), `cedar-micro` (flat Cedar-shape type
  system with full soundness proof), `cedar-full` (lift to
  `Cedar.Spec.Expr`'s 12 constructors).
- A reproducible container image
  (`ghcr.io/athanor-ai/kairos-cedar:latest`) bundling every
  toolchain (Lean 4.24.0 + 4.29.1, Rust stable, Go 1.24, Dafny
  4.9.1, cedar-policy-cli) so reviewers and customers can run the
  whole differential pipeline without host installation.

**kairos-cedar is NOT** an LLM library at runtime. The generator is
LLM-derived (program synthesis from the type-checker) but every shipped
generator is gated on a sorry-free + axiom-clean Lean soundness proof
before it joins the artefact. No machine-learning runtime, no cloud
calls, no external API keys.

LLM-driven autoformalization, multi-prover swarm orchestration, and
Aristotle integration live separately in
[`athanor-sdk`](https://github.com/athanor-ai/athanor-sdk).

## Hard rules

These come from the project's safety-critical mandate. Pull requests
that don't comply will be sent back regardless of how clever the
content is.

### 1. Never push if Lean doesn't compile

`lake build` must succeed across **all three** lake projects
(`cedar-spec-bridge`, `cedar-micro`, `cedar-full`) before any push to
any branch. The `.github/workflows/lean-build.yml` workflow runs the
same check on every push to every branch, so a broken push fails CI
visibly. Fix the build before pushing again. Don't push and "hope CI
catches it later"  - that pattern is what the workflow prevents.

Each project pins its toolchain via `lean-toolchain`:
- `cedar-spec-bridge`: Lean 4.24.0 (matches upstream `cedar-spec`)
- `cedar-micro`: Lean 4.29.1 (with Palamedes)
- `cedar-full`: Lean 4.29.1

### 2. Axiom-clean against the trusted triple

Every public theorem in `cedar-micro/CedarMicro/Soundness.lean` and
`cedar-full/CedarFull/Soundness.lean` must depend only on
`{propext, Classical.choice, Quot.sound}`  - the standard Lean kernel
axiom set. Anything else (a lingering `sorryAx`, a custom `axiom Foo`
declaration, a `@[implemented_by]` shortcut on theorem-level defs)
fails the audit. Audit a single theorem with:

```lean
#print axioms CedarMicro.Soundness.isWellTyped_iff_HasType
```

`AxiomAudit.lean` per project (tracked as a follow-up ticket in the
fleet's Linear queue) runs the audit across the public API on every
commit; CI enforces.

Sorries on scaffold files (clearly flagged in the module docstring +
excluded from the audit's import list) are acceptable as in-flight
markers, *with a tracking ticket and an active path to closure*.
Indefinite sorries decay into lies as readers forget the provisional
status  - close them or remove them.

### 3. No fake closures, no vacuous lemmas

If a tactic fires `rfl` / `unfold; grind` / `decide` / `native_decide`
and closes the goal, the goal might have been trivial as stated. Don't
ship the proof  - restate the lemma as a *by-construction invariant* or
raise the claim. We've been bitten by this before; reviewers will push
back. `native_decide` is specifically banned from anything in the
soundness umbrella (kernel-only proofs, no external compilation
reliance).

### 4. No LLM coupling in the formalization

The Lean kernel must accept your work without internet access. If your
contribution imports an HTTP client, calls a model API, or requires a
cloud key, it belongs in
[`athanor-sdk`](https://github.com/athanor-ai/athanor-sdk), not here.

The cross-prover hammer (Z3 / Dafny / EBMC / Vampire) is an exception:
those are *deterministic external solvers*, not LLMs. Their
certificates always reconstruct into Lean tactic syntax checked by the
kernel.

### 5. Native Lean shape, not library-shaped

Generators and tactics should read as Lean syntax, not as third-party
invocations. Examples of what we mean:

- ✅ `genWellTyped : (Γ : Env) → Gen Expr` (reads as a Lean
  `Gen` value, integrates with Palamedes naturally)
- ❌ `KairosCedar.Generator.run config.default` (reads as a library
  call)
- ✅ `theorem genSize_sound : ∀ e ∈ ..., isWellTyped Γ e` (reads as
  a Mathlib-style soundness statement)
- ❌ `theorem soundnessTheorem_v2_post_widening_2026_04_25` (carries
  changelog metadata in the name; goes in commit messages, not
  identifiers)

Error messages match the `cedar-spec` Lean formalisation's tone  - 
terse, actionable, no project-specific jargon.

## How to add a new schema constructor

For Lean schema-shape extensions (e.g. NEW-1 entity-shape-as-common-type
work):

1. **Read the [`docs/ROADMAP.md`](docs/ROADMAP.md)**  - the multi-phase
   plan lists the priority schema widenings. If your shape is on the
   roadmap, claim it on the relevant Linear ticket before starting.
2. **State the predicate first.** Open a *scaffold PR* that adds the
   new `JsonShape` constructor and an honest sorry on
   `wellFormedSchema` for that constructor. Mark the file excluded
   from `AxiomAudit` until closure lands.
3. **Verify against `cedar-policy 4.X`'s reference parser.** Ship at
   least three example JSON schemas matching the new shape; each must
   round-trip through `cedar translate-schema --direction
   json-to-cedar` cleanly.
4. **Close the proof.** Existing inversion lemmas in
   `cedar-spec/cedar-lean/Cedar/Validation/`. If you need a new
   inversion lemma, file as a sub-ticket and gate this PR on it.
5. **Add a Phase A probe** under `experiments/phase_i_schema_roundtrip/`
   with a fixture + result classification (clean / silent_diff /
   parse_fail).
6. **Update the per-shape table** in
   `experiments/phase_i_schema_roundtrip/SUMMARY.md` so future
   reviewers see the new shape's verdict alongside the prior ones.

## How to add a new policy generator

For `cedar-full/CedarFull/PolicyGen.lean` extensions (e.g. novelty-shape
sweeps):

1. **Define the policy shape**. Add a generator entry that produces
   one well-typed policy per input environment.
2. **State the soundness claim.** Open a scaffold PR with
   `theorem genPolicy_sound_<shape> : ∀ p ∈ genPolicy_<shape> env, isWellTyped env p`
   + an honest sorry. The `genWellTyped_sound` theorem in
   `cedar-full/CedarFull/Soundness.lean` is the umbrella; your new
   shape must compose into it.
3. **Verify against the differential harness.** Run
   `experiments/phase_c_diff/run_diff.py` at `--n 1000` minimum;
   classify results into clean / disagreement / parse_fail and file
   any disagreements at `experiments/phase_c_diff/disagreements/`.
4. **Close the proof.** Per-arm inversion lemmas using the support
   structure of `genLeaf` (canonical literals only). Sorry-free
   before merge.
5. **Add a regression test.** `tests/test_repo_hygiene.py` covers
   AI-slop / leak patterns; the soundness regression is the
   `lake build` + axiom-audit chain (CI gates).

## How to add a new evaluator

For Cedar evaluator (or extension function) verification work:

1. **Identify the spec source.** Cedar's evaluator semantics live in
   `cedar-spec/cedar-lean/Cedar/Spec/Evaluator.lean`. Bridge any new
   evaluator-side claim through `cedar-spec-bridge/CedarBridge/`.
2. **State the conformance claim.** "Evaluator X agrees with the Lean
   reference on input Y"  - open a scaffold PR with the statement +
   sorry.
3. **Verify against three oracles.** Use the Phase C three-way diff
   (Rust + Go + Lean) under `experiments/phase_c_diff/`. Disagreements
   are file-or-fix, not silently dropped.
4. **Close the proof.** Often via `Cedar.Spec.Evaluator`'s
   pattern-matching exhaustiveness; sometimes via per-extension-type
   lemmas (decimal, ipaddr, datetime, duration).
5. **Document the bug class** if a divergence surfaces. Cedar bugs we
   surface go in `experiments/phase_*/disagreements/<NAME>.md` with a
   canonical reproducer.

## Coordination protocol

Most-active channels:
- `#dev-platform` for SDK/platform infra cross-cutting
- `#dev-research` for paper / formal-method work
- `#dev-sdk` for SDK customer-facing surface
- `#agent-founder` for founder asks (do not repost without an
  explicit founder ask in the body  - defer to the dev-* channel
  matching the topic)

Internal ticket workflow:
- File the ticket *before* writing the PR title. Ticket IDs get
  reused if you guess; ask the tracker for the next number, then
  commit.
- Authorship footer convention: a one-line attribution so future
  readers see who filed the ticket. Format documented in the
  fleet's internal coordination docs.

Pinging conventions:
- Cross-fleet (research / qa / platform / cto): same channel + same
  thread, `<@UID>` mentions in body.
- Standup cadence: asabi runs the 30-min cron in
  `~/bin/cto-standup-ping.sh` (tracked in
  `athanor-builder/tools/agent-handoff/`). Reply prose, ≤4 lines, no
  fenced JSON.

PR review:
- Per the Aidan 2026-04-25 fleet rule, **one peer LGTM** from any
  other agent (`research`, `qa`, `platform`, `cto`) unblocks
  admin-merge. CI must be green; the merge state must be
  `MERGEABLE`.
- Self-approval blocked by GitHub on the shared `aidanby` account;
  LGTM lands as a comment, admin-merge is the merge mechanism.

## Reading list

- [`README.md`](README.md)  - project overview, headline result, status
  table, where-to-look index.
- [`docs/ROADMAP.md`](docs/ROADMAP.md)  - phased work plan (V1 → V4).
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)  - design decisions
  behind the three-project split.
- [`experiments/phase_c_diff/SUMMARY.md`](experiments/phase_c_diff/SUMMARY.md)
 - most-recent differential-test sweep results.
- [`cedar-spec-bridge/CedarBridge/Predicates.lean`](cedar-spec-bridge/CedarBridge/Predicates.lean)
 - the `Prop`-wrapper that lets Palamedes invert
  `Cedar.Validation.typeOf`.

## License

Apache-2.0. By submitting a PR you license your contribution under
Apache-2.0 to the project.

## Acknowledgments

This artefact would not exist in its current form without
[`cedar-policy/cedar-spec`](https://github.com/cedar-policy/cedar-spec)
(the mechanised reference),
[`hgoldstein95/palamedes-lean`](https://github.com/hgoldstein95/palamedes-lean)
(the program-synthesis tactic), and the broader Cedar engineering team
at AWS. See the [`README.md`](README.md) Acknowledgments section for
full attribution.
