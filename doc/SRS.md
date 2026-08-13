# Software Requirements Specification

## Runtime requirements

- macOS.
- A MoneyWiz SQLite database selected through an absolute `db_path` or
  global `--db` override.
- `~/.local/bin` available on `PATH` for installed commands.
- MoneyWiz Tools.app installed in the configured app location.

The build additionally requires `uv`, `swiftc`, and network access to resolve
the pinned `moneywiz-api` Git dependency when it is not already cached. No
nested or local API checkout is required. Those tools are not runtime
dependencies after the bundle is installed.

## Data requirements

- The dispatcher treats the configured path as a SQLite store.
- `db_path` may be absolute or begin with `~/`; the launcher expands a leading
  `~/` before use.
- Test fixtures and live stores can have different Core Data models.
- Live entity mappings are evidence scoped to the observed MoneyWiz model.

## Safety requirements

- Read operations must not mutate the store.
- The only verified live write is payee reassignment through the bundled Core
  Data host; other mutation paths are not product capabilities.
- Exact duplicate planning must remain read-only while the native merge
  implementation and capability are unavailable.
- `--apply` must not be run while MoneyWiz holds the persistent store open.
- Ambiguous normalized payee matches must fail closed.
- Similar-name pairs must remain pending until an explicit approval workflow
  consumes them.
- A live write must be followed by app reopen and sync confirmation.

## Portability requirements

- The installed app must contain its Python runtime, Python packages, API
  code, scripts, and Core Data host.
- Installed command symlinks must resolve inside the app bundle, not into the
  development repository.

## Compatibility requirement

Each live writer is version-scoped. A MoneyWiz model or app upgrade requires
a targeted revalidation before a previously verified operation is considered
compatible.
