# MoneyWiz Tools instructions

These rules do not apply outside of work under `moneywiz-tools/`.

## Phase branches and independent review

- Follow `doc/proposals/TRANSACTION-WRITE-IMPLEMENTATION-PLAN.md` for phase scope
  and progressive TODO refinement.
- Give each implementation phase its own `release/` branch. Create individual
  implementation branches from that phase branch using the `feat/` prefix.
- Target implementation pull requests at their owning release branch. Require
  independent code review on GitHub and resolution of actionable findings before
  merging; an implementation agent's self-review is not sufficient.
- Complete phase validation and application acceptance before phase promotion.
  A release branch name alone does not assign a version or enable capabilities.

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
