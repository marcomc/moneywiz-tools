# Improve robustness and add write helpers

## Summary

- allow MoneyWiz records to tolerate nullable metadata and noisy FX fields so reading real-world databases no longer asserts; include new RawDataHandler helper, relaxed transaction checks, and a basic unit test
- stabilize integration fixtures by explicitly targeting the repository test database and seeding default balance datasets, making the suite reproducible without a local MoneyWiz install
- add `moneywiz_api.writes.WriteSession` plus unit coverage so the CLI can preview inserts/updates/deletes and link related rows without embedding SQL in every script
- document how API consumers can set up or copy a MoneyWiz SQLite file for local development/testing via the new README section

## Technical Notes

- **Nullable metadata / tolerant invariants**: `Account.info` is typed as `Optional[str]`, `RawDataHandler.get_nullable_datetime()` mirrors the decimal helper, and `Record.__init__` now falls back to `get_datetime(0.0)` when `ZOBJECTCREATIONDATE` is absent. Transaction classes use the new `approx_equal()` helper (Decimal-backed) instead of importing `pytest`, so runtime code no longer depends on the test framework. Transfer deposit/withdraw constructors recalculate missing FX-derived fields (e.g., derive `original_amount` from sender data when zero) and relax assertions when counterpart rows carry empty currencies, matching what we see in exported databases.
- **Integration fixture stability**: `tests/integration/conftest.py` and `test_config.py` now point `TEST_DB_PATH` to `tests/test_db.sqlite` via `Path(...).resolve()` so the suite always runs against the checked-in sample DB. Default values for `CASH_BALANCES`, `HOLDINGS_BALANCES`, and `BALANCE_AS_OF_DATE` keep parametrized tests iterable even when a contributor does not maintain private datasets.
- **WriteSession helper**: `WriteSession.insert_syncobject()` calls `dict.setdefault()` for `Z_ENT` (looked up via `_ent_for`), `Z_OPT` (defaults to `1`), `ZGID` (random UUID uppercased), and `ZOBJECTCREATIONDATE` (current timestamp converted through `get_date`). All statements are recorded in `self._planned` so CLI tools can show preview SQL before the connection commits. Convenience methods wrap recurring SQL for assigning categories/tags and linking refund rows; `tests/unit/test_writes_preview.py` verifies that dry-run planning enqueues the expected insert statement.
- **README guidance**: the "Using a Test Database" section explains how to point `MoneywizApi` at a personal export, work from a copy, or ship a sanitized fixture under `tests/`, clarifying for downstream developers that read-only operations are safe while explicit write helpers opt into mutations.

## Testing

- unit tests covering RawDataHandler helpers and WriteSession insert planning
- integration suite exercises run against `tests/test_db.sqlite`

## Disclaimer

- Code generation involved GitHub Copilot GPT-5-Codex, but every change was reviewed, adjusted, and tested manually before inclusion.

## Breaking Changes

- None. All changes maintain backward compatibility; runtime APIs behave the same aside from now tolerating missing metadata/FX fields, and WriteSession is additive.
