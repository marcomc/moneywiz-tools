# Technical Design Document (TDD)

## Architecture

- API (moneywiz-api):
  - Read: `DatabaseAccessor`, per-entity managers, typed models constructed from `ZSYNCOBJECT` rows; auxiliary tables for relationships.
  - Write: `writes.WriteSession` for planned SQL (dry-run/apply), plus future typed create/update helpers.
- CLI: `moneywiz.sh` dispatcher invoking Python scripts under `scripts/` with `PYTHONPATH=moneywiz-api/src`.

## Data Model

- Central table: `ZSYNCOBJECT` (SyncObject), typed via `Z_ENT` ↔ `Z_PRIMARYKEY.Z_NAME`.
- Relationships: `ZCATEGORYASSIGMENT`, `Z_36TAGS`, `ZWITHDRAWREFUNDTRANSACTIONLINK`, `ZUSER`.
- Conversions: timestamps via `utils.get_datetime/get_date`; amounts via `RawDataHandler.get_decimal`.

## Modules

- `database_accessor.py`: low-level queries, type maps, relationship loaders.
- `managers/*`: caches and exposes domain-specific helpers.
- `model/*`: typed dataclasses mapping raw fields; tolerances for legacy data; validations where stable.
- `writes.py`: library write session with SQL planning and execution; helpers for common relationships (imported by per-command scripts).
- `scripts/*`: focused CLIs for each function; each write action has its own script (insert.py, update.py, delete.py, safe_delete.py, rename.py, assign_categories.py, assign_tags.py, link_refund.py).

## Write Session Design

- `WriteSession(db_path, dry_run=True)`: records `PlannedSQL` steps; executes only with `--apply`.
- `insert_syncobject(typename, fields)`: resolves `Z_ENT`, auto-fills `ZGID`, `Z_OPT`.
- `update_syncobject(pk, fields)`: updates arbitrary columns.
- `delete_syncobject(pk)`: removes rows by PK (guarded by caller policy).
- Relationship helpers: `assign_categories`, `assign_tags`, `link_refund`.
- Transactions: context manager available; future writes will group multi-step operations.

## Validations & Safety

- Category splits must sum to transaction amount (by sign) — to be enforced in typed helpers.
- Transfers must create paired rows with coherent FX/fees and cross-links.
- Refund links must reference existing withdraw transactions.
- Dry-run by default; `--apply` is explicit; recommend operating on DB copies while maturing.

## Testing Strategy

- Unit tests on mapping/conversion functions (`RawDataHandler`, epoch conversion).
- Integration tests against a readonly test DB copy for read flows.
- Preview tests for write session to assert correct SQL/plans.
- (Optional) Apply-mode tests use a temp SQLite copy seeded from fixtures.

## Test Suite Layout (scaffolded)

- API unit tests: `moneywiz-api/tests/unit/`
  - `test_raw_data_handler.py`: conversions and edge cases.
  - `test_writes_preview.py`: SQL planning for inserts/updates.
- API integration tests: `moneywiz-api/tests/integration/` (existing).
- CLI tests: `tests/cli/`
  - `test_users.py`: verifies JSON output contract of `moneywiz.sh users`.

## Running Tests

- Script: `scripts/run_tests.sh`
  - Ensures `.venv` via uv, installs pytest, sets `PYTHONPATH`, then runs:
    - `pytest -q moneywiz-api/tests`
    - `pytest -q tests`
- Manual:
  - `PYTHONPATH=moneywiz-api/src .venv/bin/python -m pytest -q moneywiz-api/tests`
  - `PYTHONPATH=moneywiz-api/src .venv/bin/python -m pytest -q tests`

Developer workflow: run `scripts/run_tests.sh` after any API change or when adding CLI options/parameters to ensure no regressions.

## Extensibility

- Add typed create/update helpers per entity on top of `WriteSession`.
- Keep field mappings in `doc/FIELD-MAPPINGS.md` aligned with models as they evolve.
- Extend CLI with new subcommands; update usage and README with each change.
