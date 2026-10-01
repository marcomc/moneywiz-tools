# MoneyWiz Tools instructions

These rules do not apply outside of work under `moneywiz-tools/`.

## Phase branches and independent review

- Follow `doc/proposals/TRANSACTION-WRITE-IMPLEMENTATION-PLAN.md` for phase scope
  and progressive TODO refinement.
- The confirmed `0.3.0` scope is the full P0/P1F/P1/P2/P3 writing roadmap,
  including W01–W09. Keep each operation in a separate `feat/` branch and PR
  targeting `release/0.3.0`; phase labels describe dependencies and review scope,
  not separate release branches.
- Require independent code review on GitHub and resolve actionable findings.
  Leave each new PR open for the user to inspect and merge; do not merge it on
  the user's behalf. An implementation agent's self-review is not sufficient.
- Run `$scoped-pre-pr-remediation` before committing/pushing the final changes
  and creating a PR. Then run `$codex-pr-review-remediation-loop`, reusing the
  same coordinator and ledger until local readiness and current-head remote
  clean evidence agree. Do not duplicate active review requests or monitors.
- Complete phase validation and application acceptance before phase promotion.
  A release branch name alone does not assign a version or enable capabilities.
- For dependency-pin or write-capability changes, run the opt-in installed
  bundle suite and review every direct native mutation entry point. Each path
  for a fixture-only operation must enforce the disposable-store marker checked
  by the Python client. Approved live operations must independently check the
  reviewed app, model and store identity before writing.
- For installed native validation, set both `MONEYWIZ_TEST_APP_PATH` and
  `MONEYWIZ_TEST_MODEL_PATH`, then inspect every skip and map it to its fixture
  producer. Keep the disposable-marker producer distinct from unmarked
  negative fixtures; an otherwise successful bundle-only run is not admission
  evidence. Inspect the persisted fixture entities and relationships before
  selecting an operation; do not change production admission to accommodate
  an invalid fixture. Assert the reviewed runtime-edition admission contract.
- Isolate installed native-test journal and plan identities per store. Before
  retrying an unknown outcome, inspect journal preimages and compare pre-write
  and post-failure financial rows to establish whether a mutation occurred.
- Run integrated Python validation with
  `uv run --with pytest python -m pytest`; this keeps pytest and project
  dependencies on the same interpreter when pytest is not a declared dependency.
- For cross-language native write plans, accept only exact supported scalar
  types and apply the same whitespace-normalization predicate at every Python
  ingress check and native decoding boundary. Capture input bytes once, then
  parse and hash that same capture; cover cross-runtime boundary values plus
  source changes between digest and parsing with positive and negative tests.
- When enabling or changing a writer capability, update the minimum active
  operator, release, design, and mapping documentation consumers, while
  preserving historical and legacy-exclusion records. Test its positive and
  negative cases on the runtime and store edition that each case supports.
- Treat fixture cache deltas as fixture semantics, not evidence of live account
  balances. Before adding a balance guard, compare account cache, opening
  balance, full ledger, and application display; cover supported account
  subtypes and backdated cash history.
- For retained Core Data transformables, preserve the finite observed archive
  contract rather than accepting generic serializable shapes. Cover persisted
  positive, refusal, apply/recovery, and retained-dependency paths; reject
  unobserved key and value types even if generic serialization would succeed.

## Distributable bundle validation

- Inspect generated manifests and native binary bytes for build-path disclosure
  in addition to runtime self-containment. Scan symlink targets as well as
  regular-file bytes, and require portable aliases to resolve relatively within
  the bundle. Test each implicated producer and corroborate the result with a
  fresh rebuilt artifact. Keep privacy, runtime portability, and application
  acceptance as separate evidence.
- When adding a runtime payload to a bundle manifest, update every copied-source
  publication fixture in the same change. Run its publication tests before the
  full suite, including while the new payload is untracked.

## Reconciliation skill and private context

- Use `$moneywiz-reconcile` for live account verification and reconciliation.
  Its canonical source is `~/.agents/skills/moneywiz-reconcile/SKILL.md`.
- Load the private `MoneyWiz/User profile and session.md` in the canonical
  Obsidian vault before live work. Read current policies first; older checkpoints
  are historical evidence, not repeat-write instructions.
- The companion `MoneyWiz/Session analysis 2026-09-09.md` records resolved
  contradictions and source provenance. Personal data stays in the private vault,
  outside the generic skill and repository documentation.

## Live financial-app sessions

- **Absolute rule for every live import or reconciliation:** keep iPhone
  Mirroring active even while using the CLI, MoneyWiz, or a browser. Perform a
  harmless real pointer movement or click in the mirrored window at least every
  45 seconds, and immediately after any prolonged external task. A screenshot
  or accessibility read alone does not count as an interaction.
- Treat preventing an iPhone app timeout as the agent's responsibility. Do not
  wait for the user to remind or re-unlock it unless the phone itself requires
  authentication.

## MoneyWiz API subtree instructions

These rules apply only to work under `moneywiz-api/`.

- When diagnosing account-read or schema failures, trace and reproduce the
  first failing expression before attributing the final exception to schema
  drift. Diagnostic paths must not serialize partially initialized models;
  distinguish nullable metadata from required identity and validate it after
  construction.
- Database-backed integration tests must be opt-in through
  `MONEYWIZ_TEST_DB_PATH`. Skip them when the variable is absent, validate an
  explicit path read-only before model creation, and never inherit a user
  database path from production CLI defaults.
- Schema profiles must define aliases per consumer or operation. Do not infer
  one global active alias from physical column presence when holdings and
  transactions can use different columns; cover mixed-layout regressions.
- Keep schema nullability aligned with the model type and validator contract.
  Relax conversion only for an evidenced legacy shape with a regression test;
  do not generalize an observed zero value into unobserved NULL acceptance.
