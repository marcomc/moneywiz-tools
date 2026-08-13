# Changelog

## [0.2.0] - 2026-08-09

### Added

- A relocatable MoneyWiz Tools.app installation path with bundled Python runtime, scripts, API source, and Core Data host.
- A documented, evidence-backed Core Data writer for live payee reassignment and destination-payee creation.
- Version-scoped live payee structure and relationship documentation, including transaction and string-history references.
- Exact-normalized duplicate-payee planning with deterministic canonical
  selection.
- An editable, approval-only CSV map for similar-name payee candidates.

### Changed

- Reorganized operator and maintainer documentation around the installed bundle, command roles, and live-write boundaries.
- Added source-backed installation and live-write workflow diagrams.
- Consolidated the supported interface on the configuration-aware `moneywiz`
  dispatcher; `moneywiz-cli` remains an explicit-path API shell, while generic
  raw-SQL mutation commands are retired from the product surface.
- Replaced the nested runtime API checkout with the pinned Git dependency and
  locked build graph; no nested checkout is required for the installed bundle.
- Added a versioned profile-by-capability register: live payee reassignment is
  enabled only for verified profiles, while duplicate-payee merge remains
  planning-only pending separate acceptance evidence.
- Recorded the proposed merge survivor contract and the evidence still needed
  before a native merge implementation can be enabled.
- Aligned operator and design documentation with the current boundaries,
  including `~/` configuration-path expansion.

### Fixed

- Removed stale guidance that described the project as read-only or presented generic raw SQLite writes as live-store compatible.
- Documented configuration path handling, including launcher expansion of a
  leading `~/` value.
- Replaced obsolete test-wrapper references with the actual validation strategy.
- Made setup and test-database seeding discover the current MoneyWiz 2026
  store before falling back to the legacy store path, while preserving
  explicit and configured database choices.
- Made empty and already-satisfied apply plans validate their write capability
  without invoking process, model, writer, or native-host preflight.
- Made normalized new-payee groups deterministic and resolved both
  extensionless and `.mom` model-manifest leaves without duplicate suffixes.
- Limited quadratic similar-name comparisons to explicit `--fuzzy-map` exports
  and distinguished skipped analysis from an empty result.
- Escaped direct, compatibility-normalized, and whitespace/control-prefixed
  formula-like payee names in both fuzzy-review CSV name columns.
- Added schema capability profiles and investment-column aliases for fixture
  and MoneyWiz 2026 live-store layouts.
- Moved installed schema-export defaults to the user data directory while
  preserving explicit paths and source-tree defaults.
- Restricted bundle payload assembly to one exact runtime manifest and tracked
  documentation, excluding development/build inputs, tests, and local data.
- Added dependency-free installed version reporting from application metadata.
- Made read-only transfer parsing tolerate live-profile zero-valued
  `ZORIGINALAMOUNT` when counterparty amount and exchange rate are present.
- Made read-only API loading isolate malformed or model-incompatible records
  instead of aborting unrelated listing commands with a traceback.
- Made optional category, refund, and tag relationship tables safe to omit in a
  supported store profile.

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
