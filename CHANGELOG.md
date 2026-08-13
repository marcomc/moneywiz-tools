# Changelog

## [Unreleased]

### Changed

- Consolidated the end-user interface on the `moneywiz` command and retired
  product support for `moneywiz-cli` and generic raw-SQL mutation commands.
- Replaced the nested runtime API checkout with a pinned Git dependency and
  locked build graph.
- Added a versioned `profile x capability` register: live payee reassignment
  is enabled only for verified database profiles, while duplicate-payee merge
  application is explicitly blocked pending separate acceptance evidence.
- Aligned operator and design documentation with the current boundaries:
  duplicate merge is planning-only, `~/` config paths are expanded, and the
  pinned `moneywiz-api` Git dependency needs no nested checkout.

### Fixed

- Made setup and test-database seeding discover the current MoneyWiz 2026
  store before falling back to the legacy store path, while preserving
  explicit and configured database choices.
- Made empty and already-satisfied apply plans validate their write capability
  without invoking the MoneyWiz process check, model resolver, writer resolver,
  or native host.
- Made normalized new-payee groups use one deterministic display name and made
  the model resolver handle both extensionless and `.mom` manifest leaves
  without duplicating the extension.
- Limited quadratic similar-name comparisons to explicit `--fuzzy-map`
  exports, while distinguishing a skipped analysis from an empty result.
- Escaped direct, compatibility-normalized, and whitespace- or control-prefixed
  formula-like payee names in both fuzzy-review CSV name columns so spreadsheet
  applications treat them as literal data.
- Added schema capability profiles and investment-column aliases so read-only
  commands support both suffixed fixture columns and the unsuffixed columns
  observed in the MoneyWiz 2026 live store.
- Moved installed schema-export defaults to the user data directory while
  preserving explicit output paths and source-tree development defaults.
- Restricted bundle payload assembly to one exact runtime-program manifest and
  separately selected tracked documentation, excluding development and build
  inputs, tests, and ignored or untracked databases, SQLite sidecars, logs,
  caches, and scratch files.
- Fixed dependency-free installed version reporting from the application
  bundle metadata.
- Made read-only transfer parsing tolerate the live profile's zero-valued
  `ZORIGINALAMOUNT` when the counterparty amount and exchange rate are present.
- Made read-only API loading isolate malformed or model-incompatible records
  instead of aborting unrelated listing commands with a traceback.
- Made optional category, refund, and tag relationship tables safe to omit in a
  supported store profile.

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
- Distinguished the configuration-aware `moneywiz` dispatcher from the explicit-path `moneywiz-cli` API shell.
- Recorded the proposed merge survivor contract and the evidence still needed
  before a native merge implementation can be enabled.

### Fixed

- Removed stale guidance that described the project as read-only or presented generic raw SQLite writes as live-store compatible.
- Documented configuration path handling, including launcher expansion of a
  leading `~/` value.
- Replaced obsolete test-wrapper references with the actual validation strategy.

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
