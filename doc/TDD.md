# Technical Design Document

## Architecture

~~~text
moneywiz or moneywiz-cli
          |
          v
~/.local/bin symlink
          |
          v
MoneyWiz Tools.app
  |- Python runtime and virtual environment
  |- moneywiz-api source and dispatcher scripts
  `- MoneyWizTools Swift Core Data host
~~~

`moneywiz` is the product dispatcher. `moneywiz-cli` is a separate upstream
read-only API shell that receives an explicit database path.

## Build design

Make owns the supported build and installation workflow:

1. Validate `uv`, `swiftc`, and the local `moneywiz-api/` source.
2. Build or refresh MoneyWiz Tools.app.
3. Copy the runtime, scripts, and API source into the bundle.
4. Create the requested command symlink in `~/.local/bin`.

`make install` creates the `moneywiz` link. `make install-cli` creates the
`moneywiz-cli` link. Both ensure the app bundle exists.

## Data-access design

| Path | Mechanism | Scope |
| --- | --- | --- |
| Reads | SQLite/API access | Live or copied store. |
| Generic mutations | SQL-oriented helpers | Test copy only. |
| Payee reassignment | Bundled Swift Core Data host | Verified live path. |
| Exact duplicate consolidation | Bundled Swift Core Data host | Revalidate before first live batch. |

The live writer relies on Core Data to manage object identity, optimistic
versions, persistent history, and the sync-visible save lifecycle. It is
therefore intentionally narrower than the generic SQL helpers.

For exact duplicate groups, the host discovers each modeled relationship whose
destination is `Payee`, migrates to-one and to-many references to the chosen
survivor, verifies no supported inbound reference remains, then deletes the
source object in the same save.

## Validation strategy

Documentation and command behavior must agree with `make` and
`moneywiz --help`. The project has no documented `scripts/run_tests.sh`
wrapper; do not publish that nonexistent command.

For each new live writer, validation must include:

1. A minimal native-app comparison for the target operation.
2. A narrow writer execution against the compatible model.
3. App reopen after the write.
4. Persistent-history and sync observation.
5. Cleanup or restoration of any transaction created only for testing.

The current writer evidence is recorded in
[Live Write Compatibility](LIVE-WRITE-COMPATIBILITY.md).
