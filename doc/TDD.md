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
| Exact duplicate consolidation | Bundled Swift Core Data host | Planned, capability blocked. |

The live writer relies on Core Data to manage object identity, optimistic
versions, persistent history, and the sync-visible save lifecycle. A Python
preflight must identify a known profile and a verified named capability before
the host is launched.

For exact duplicate groups, the host discovers each modeled relationship whose
destination is `Payee`, migrates to-one and to-many references to the chosen
survivor, verifies no supported inbound reference remains, then deletes the
source object in the same save.

## Validation strategy

Documentation and command behavior must agree with `make` and
`moneywiz --help`. Run `scripts/run_tests.sh` to synchronize the frozen locked
dependency graph and execute the MoneyWiz Tools CLI regression suite. The
wrapper does not depend on or test a nested `moneywiz-api` checkout.

For each new live writer, validation must include:

1. A minimal native-app comparison for the target operation.
2. A narrow writer execution against the compatible model.
3. App reopen after the write.
4. Persistent-history and sync observation.
5. Cleanup or restoration of any transaction created only for testing.

The current writer evidence is recorded in
[Live Write Compatibility](LIVE-WRITE-COMPATIBILITY.md).
