# Changelog

## [Unreleased]

## [0.1.0] - 2026-02-23

### Added

- CLI bootstrap workflow with `--setup` and a generated config template (`.moneywizrc.example`).
- Write-capable CLI operations for core `ZSYNCOBJECT` entities:
  - `insert`, `update`, `delete`, `safe-delete`, `rename`
  - `assign-categories`, `assign-tags`, `link-refund`
  - `reassign-payees-by-id`
- Payee tooling enhancements:
  - `payees --sort-by-name`
  - payee reassignment by transaction description with per-user matching and on-demand payee creation.
- Test database lifecycle commands:
  - `create-test-db`
  - `sanitize-test-db`
- Sanitization reporting with verbose per-column summaries.
- Test/automation utilities and fixtures:
  - CLI regression tests for transactions/payees/schema/users flows
  - `scripts/run_tests.sh` helper flow
  - bundled Italian sample dataset (`transactions.ita.json`).

### Changed

- Unified write-script execution model around explicit dry-run vs apply behavior across update/delete/assign/link/rename/reassign flows.
- `create-test-db` now supports reusing the configured database path from user config.
- `reassign-payees-by-id` now supports broader targeting and routing options:
  - selector-based processing (`--from-payee-id`, `--from-empty-payee`)
  - empty-description fallback assignment (`--empty-desc-target-payee-id`)
  - empty-payee processing scoped to payee-relevant income/expense transaction types.
- CLI help/usage output expanded to surface the newer test-db and reassignment workflows.

### Documentation

- Refreshed top-level docs (`README.md`, `TODO.md`, `FUNCTIONS.md`, `PR_DESCRIPTION.md`) and aligned command examples.
- Expanded project design and data-model documentation in `doc/` (`SRS`, `FSD`, `TDD`, concepts, schema, ER diagram, field mappings, extension notes, repo integration).
- Clarified custom DB selection and sanitization behavior in command docs/help text.
- Updated project credits.

### Legal

- Added `LICENSE` (MIT).
