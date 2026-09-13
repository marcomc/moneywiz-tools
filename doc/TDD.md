# Technical Design Document

## Architecture

~~~text
moneywiz
          |
          v
~/.local/bin symlink
          |
          v
MoneyWiz Tools.app
  |- Python runtime and virtual environment
  |- locked moneywiz-api dependency and dispatcher scripts
  `- MoneyWizTools Swift Core Data host
~~~

`moneywiz` is the sole product dispatcher.

## Build design

Make owns the supported build and installation workflow:

1. Validate `uv`, `swiftc`, `pyproject.toml`, and `uv.lock`.
2. Build or refresh MoneyWiz Tools.app.
3. Install the locked dependency graph and scripts into the bundle.
4. Create the `moneywiz` symlink in `~/.local/bin`.

`make install` creates the `moneywiz` link and ensures the app bundle exists.

## Data-access design

| Path | Mechanism | Scope |
| --- | --- | --- |
| Reads | SQLite/API access | Live or copied store. |
| Payee reassignment | Bundled Swift Core Data host | Verified live path. |
| Exact duplicate planning | Python planner | Available; native apply is not implemented. |

The live writer relies on Core Data to manage object identity, optimistic
versions, persistent history, and the sync-visible save lifecycle. A Python
preflight must identify a known profile and a verified named capability before
the host is launched.

For exact duplicate groups, the Python command selects deterministic canonical
payees and reports the proposed merges. The Swift host does not migrate inbound
relationships or delete source payees, and the capability gate rejects apply
attempts.

## Validation strategy

Documentation and command behavior must agree with `make` and
`moneywiz --help`. Run `scripts/run_tests.sh` to synchronize the frozen locked
dependency graph and execute the MoneyWiz Tools CLI regression suite. The
dependency is fetched from the pinned `moneywiz-api` Git revision; no nested or
local API checkout is required.

For documentation-only or release-preparation changes, validate the reader
path as well as the implementation: run `make check-deps`, inspect top-level
and command-specific help, verify `moneywiz --version`, run the CLI tests, and
check changed Markdown with the repository Markdown configuration. Release
notes should describe user-visible capability and behavior, not commit order.

After building a candidate bundle, run the opt-in installed-runtime smoke test:

~~~sh
MONEYWIZ_TEST_BUNDLE_PATH="$HOME/Applications/MoneyWiz Tools.app" \
  MONEYWIZ_TEST_MODEL_PATH="/Applications/MoneyWiz.app/Contents/Resources/MoneyWizDataModel.momd/MoneyWizDataModel 48.mom" \
  .venv/bin/python -m pytest -q tests/cli/test_installed_bundle_smoke.py
~~~

The test invokes that bundle's launcher, Python runtime and native host from an
unrelated working directory with Python environment overrides removed. It uses
only a temporary synthetic SQLite store and an isolated home directory; it does
not discover or open the configured user database. The explicit model path is
read only: the native host checks a valid compiled model checksum without
opening a store, and separately proves that a missing model fails with a bounded
error. Without `MONEYWIZ_TEST_BUNDLE_PATH`, the installed-runtime tests are
skipped. Without `MONEYWIZ_TEST_MODEL_PATH`, only the valid-model checksum test
is skipped; the launcher and native negative-path checks still run. The fast
bundle-publication tests remain separate.

For each new live writer, validation must include:

1. A minimal native-app comparison for the target operation.
2. A narrow writer execution against the compatible model.
3. App reopen after the write.
4. Persistent-history and sync observation.
5. Cleanup or restoration of any transaction created only for testing.

The current writer evidence is recorded in
[Live Write Compatibility](LIVE-WRITE-COMPATIBILITY.md).
