# MoneyWiz Tools

MoneyWiz Tools is a macOS command-line toolkit for inspecting a MoneyWiz
SQLite store and performing one verified live payee-reassignment workflow
through Core Data.

## Table of Contents

- [Install](#install)
- [Configure the database](#configure-the-database)
- [Read data](#read-data)
- [Write data](#write-data)
- [Use the interactive API shell](#use-the-interactive-api-shell)
- [Work on a test copy](#work-on-a-test-copy)
- [Documentation](#documentation)
- [Development](#development)

## Install

The installed product is **MoneyWiz Tools.app** plus lightweight command
symlinks. The bundle contains its Python runtime, packages, scripts, and
Core Data host, so using it does not depend on this development checkout,
pyenv, uv, or a system Python.

Build-time prerequisites:

- macOS with `swiftc` available through Xcode Command Line Tools.
- `uv`.
- This checkout, including the `moneywiz-api/` source directory.

Run `make` first to see the complete target list, then install the commands
you need:

~~~sh
make
make install
make install-cli
~~~

`make install` builds or refreshes the app bundle and installs `moneywiz`.
`make install-cli` builds or refreshes the same bundle and installs
`moneywiz-cli`. Both commands can be run independently.

The default bundle destination is `~/Applications/MoneyWiz Tools.app`. To use
another parent directory, persist it before installing:

~~~sh
make configure-install-dir APP_BUNDLE_DIR="$HOME/LocalApps"
make install
~~~

Ensure `~/.local/bin` is on `PATH`.

## Configure the database

Create or edit `~/.moneywizrc` and set an absolute database path:

~~~ini
db_path=/Users/your-user/Library/Containers/com.moneywiz.personalfinance-setapp/Data/Library/Application Support/MoneyWiz_iCloud.sqlite
~~~

The shown location is the currently observed Setapp MoneyWiz 2026 store.
Treat it as an example: confirm the actual store on the machine where the
tool runs.

Do not use `~` in `db_path`. The launcher does not expand it, so SQLite sees
it as a literal directory name. A global command-line override always takes
precedence:

~~~sh
moneywiz --db /absolute/path/to/MoneyWiz_iCloud.sqlite payees
~~~

## Read data

Use `moneywiz --help` for the authoritative command list. Common read-only
operations include:

~~~sh
moneywiz users
moneywiz accounts
moneywiz categories
moneywiz payees
moneywiz transactions
moneywiz summary
moneywiz schema
~~~

`moneywiz.sh` is the source-tree dispatcher used during development. The
installed `moneywiz` command invokes the equivalent dispatcher from inside
MoneyWiz Tools.app.

## Write data

There are two deliberately separate write scopes.

| Scope | Supported use |
| --- | --- |
| Test copy or disposable database | Generic SQL-oriented insert, update, delete, category, tag, and refund helpers. |
| Live MoneyWiz iCloud store | Payee reassignment and exact duplicate-payee consolidation through the bundled Core Data host. |

The live Core Data operations first produce a plan, then write only when
`--apply` is supplied:

~~~sh
moneywiz reassign-payees-by-id --from-payee-id 1234 --show-plan
# Quit MoneyWiz before the next command.
moneywiz reassign-payees-by-id --from-payee-id 1234 --apply
~~~

Exact normalized duplicates have a separate consolidation command. It chooses
the readable canonical spelling deterministically, merges exact groups only,
and exports near-name candidates for manual approval:

~~~sh
moneywiz merge-duplicate-payees --show-plan \
  --fuzzy-map "$HOME/payee-fuzzy-review.csv"
~~~

The reassignment command can reuse an existing destination payee or create one
from the transaction description. It refuses ambiguous normalized matches
rather than choosing a duplicate silently.

Do not treat a successful raw SQLite `--apply` operation as proof that it is
safe for the live iCloud store. Direct live reassignment has a separate Core
Data history and CloudKit contract documented in
[Core Data Writer](doc/CORE-DATA-WRITER.md) and
[Live Write Compatibility](doc/LIVE-WRITE-COMPATIBILITY.md).
The exact-duplicate policy and the approval-only fuzzy map are documented in
[Payee Consolidation](doc/PAYEE-CONSOLIDATION.md).

## Use the interactive API shell

`moneywiz-cli` is the upstream read-only API shell. It takes an explicit
database path and does not read `~/.moneywizrc`:

~~~sh
moneywiz-cli /absolute/path/to/MoneyWiz_iCloud.sqlite
~~~

It is not the command dispatcher, so `moneywiz-cli payees` is interpreted as
a database path and fails. Use `moneywiz payees` for command output or
`moneywiz shell` for the configuration-aware interactive path.

## Work on a test copy

Use the test-database commands when developing or inspecting generic write
helpers:

~~~sh
moneywiz create-test-db
moneywiz sanitize-test-db
~~~

Keep experiments that use raw SQL on a copied or generated store. Live
compatibility is established per operation, not inherited from the test-copy
helpers.

## Documentation

| Need | Document |
| --- | --- |
| Install, relocate, or remove the app | [Bundle Installation](doc/BUNDLE-INSTALLATION.md) |
| Understand the live writer | [Core Data Writer](doc/CORE-DATA-WRITER.md) |
| Operate and revalidate live writes | [Live Write Compatibility](doc/LIVE-WRITE-COMPATIBILITY.md) |
| Inspect the verified live payee model | [Live Payee Structure](doc/LIVE-PAYEE-STRUCTURE.md) |
| Consolidate exact duplicates and review similar names | [Payee Consolidation](doc/PAYEE-CONSOLIDATION.md) |
| Navigate all project documents | [Documentation Index](doc/README.md) |
| Find command roles and examples | [Functions Reference](FUNCTIONS.md) |

## Development

Use `make` as the entry point for supported build and installation targets.
The source tree contains the dispatch scripts, the API source, and the Swift
host that are assembled into the relocatable app bundle.
