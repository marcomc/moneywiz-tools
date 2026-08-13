# MoneyWiz Tools

MoneyWiz Tools is a macOS command-line toolkit for inspecting a MoneyWiz
store and performing verified, profile-gated live writes through Core Data.

## Table of Contents

- [Install](#install)
- [Configure the database](#configure-the-database)
- [Read data](#read-data)
- [Write data](#write-data)
- [Check compatibility](#check-compatibility)
- [Use the interactive read shell](#use-the-interactive-read-shell)
- [Documentation](#documentation)
- [Development](#development)

## Install

The installed product is **MoneyWiz Tools.app** plus lightweight command
symlinks. The bundle contains its Python runtime, packages, scripts, and
Core Data host, so using it does not depend on this development checkout,
pyenv, uv, or a system Python.

Build-time prerequisites:

- macOS with `swiftc` available through Xcode Command Line Tools.
- Git and a Git worktree for selecting the tracked bundle payload.
- `uv`.
- This checkout, including `pyproject.toml` and `uv.lock`.

Install from a clean checkout on macOS. The build requires `git`, `uv`, and
`swiftc`; users do not need Python, `pyenv`, or `uv` after installation.

Check the available targets, validate the build prerequisites, then install:

~~~sh
make
make check-deps
make install
moneywiz --version
moneywiz --help
~~~

`make install` builds or refreshes the app bundle and installs `moneywiz`.
It also removes a legacy `moneywiz-cli` symlink if one is present.
`moneywiz` is the only supported end-user command.

The default bundle destination is `~/Applications/MoneyWiz Tools.app`. To use
another parent directory, persist it before installing:

~~~sh
make configure-install-dir APP_BUNDLE_DIR="$HOME/LocalApps"
make install
~~~

Ensure `~/.local/bin` is on `PATH`.

To update an existing installation, pull or check out the desired revision and
run `make install` again. The build stages and validates a replacement bundle
before promotion and restores the previous bundle if promotion fails.

To remove the installed app and command links, run:

~~~sh
make uninstall
~~~

`make clean` is an alias for this removal operation; it does not clean build
artifacts from the source tree.

## Configure the database

Create or edit `~/.moneywizrc` and set an absolute database path:

~~~ini
db_path=/Users/your-user/Library/Containers/com.moneywiz.personalfinance-setapp/Data/Library/Application Support/MoneyWiz_iCloud.sqlite
~~~

The shown location is the currently observed Setapp MoneyWiz 2026 store.
Treat it as an example: confirm the actual store on the machine where the
tool runs.

`moneywiz --setup` probes that current location first and the legacy
`Data/Documents/.AppData/ipadMoneyWiz.sqlite` location second. It records the
first existing store in a new `~/.moneywizrc`, or leaves the current location
commented for manual correction when neither exists. An existing config is
never replaced.

`db_path` may use `~`; the launcher expands it before opening the database.
A global command-line override always takes precedence:

~~~sh
moneywiz --db /absolute/path/to/MoneyWiz_iCloud.sqlite payees
~~~

## Read data

Use `moneywiz --help` for the authoritative command list. The installed
interface has four command groups:

| Group | Commands | Access |
| --- | --- | --- |
| Reads | `users`, `accounts`, `categories`, `payees`, `tags`, `transactions`, `holdings` | Read-only database access |
| Writes and plans | `reassign-payees-by-id`, `merge-duplicate-payees` | Dry-run by default; live apply is capability-gated |
| Introspection | `compatibility`, `schema`, `summary`, `stats`, `record` | Read-only inspection and reports |
| Interactive | `shell` | Read-only API shell |

Common read-only operations include:

~~~sh
moneywiz users
moneywiz accounts
moneywiz categories --user 1
moneywiz payees
moneywiz transactions
moneywiz summary
moneywiz schema
~~~

`moneywiz.sh` is the source-tree dispatcher used during development. The
installed `moneywiz` command invokes the equivalent dispatcher from inside
MoneyWiz Tools.app.

Without explicit output paths, installed `moneywiz schema` exports to
`${XDG_DATA_HOME:-$HOME/.local/share}/moneywiz-tools/schema`. The source-tree
dispatcher keeps the development defaults under `doc/`. `--out-md` and
`--out-json` override either default.

## Write data

The product has no generic raw-SQL mutation command. Every live write uses the
bundled Core Data host, requires `--apply`, and is admitted only when the
detected schema profile lists that operation as `verified`:

~~~sh
moneywiz reassign-payees-by-id --from-payee-id 1234 --show-plan
# Quit MoneyWiz before the next command.
moneywiz reassign-payees-by-id --from-payee-id 1234 --apply
~~~

Exact normalized duplicates can be planned and near-name candidates exported:

~~~sh
moneywiz merge-duplicate-payees --show-plan \
  --fuzzy-map "$HOME/payee-fuzzy-review.csv"
~~~

The corresponding live merge capability is currently blocked pending separate
Core Data acceptance evidence. The native host does not implement relationship
migration or source-payee deletion. Use MoneyWiz 2026's
`Preferences > Payees > Edit` merge action for approved pairs. The fuzzy CSV
is review-only; see [Functions Reference](FUNCTIONS.md) for the decision flow.

The reassignment command can reuse an existing destination payee or create one
from the transaction description. It refuses ambiguous normalized matches
rather than choosing a duplicate silently.

Direct live reassignment has a separate Core Data history and CloudKit contract
documented in
[Core Data Writer](doc/CORE-DATA-WRITER.md) and
[Live Write Compatibility](doc/LIVE-WRITE-COMPATIBILITY.md).
The exact-duplicate policy and the approval-only fuzzy map are documented in
[Payee Consolidation](doc/PAYEE-CONSOLIDATION.md).

## Check compatibility

Inspect the detected schema profile and its operation capabilities before a
write:

~~~sh
moneywiz compatibility
moneywiz compatibility --capability write.reassign-payees-by-id
moneywiz compatibility --format json
~~~

An unknown profile is diagnostic-only. Profile selection includes the exact
Core Data model checksum, so a future model that retains the same tables and
columns is not treated as the verified model. A listed operation may be
`verified`, `supported`, or `blocked`; only `verified` permits a live write.
Table and JSON output use the same nonzero status for unknown profiles and
blocked or unknown requested capabilities.

## Use the interactive read shell

`moneywiz shell` starts the configuration-aware interactive read path.
`moneywiz-cli` is not a supported product entry point.

The source checkout also exposes `create-test-db` and `sanitize-test-db` for
disposable development fixtures. They are intentionally not included in the
installed product. See [Functions Reference](FUNCTIONS.md) for the complete
command table and exact examples.

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
The source tree contains the dispatch scripts, the compatibility register, and
the Swift host. The locked API dependency graph uses the pinned `moneywiz-api`
Git revision in `pyproject.toml`; no nested or local API checkout is required.
It is assembled into the relocatable app bundle. Bundle publication selects
runtime programs from one explicit product manifest, copies tracked
documentation separately, and adds the required launcher/configuration files.
Development helpers and build inputs, tests, local databases, SQLite sidecars,
logs, caches, and other untracked files are not installed. The `create-test-db`
and `sanitize-test-db` commands remain available only through the source-tree
dispatcher.
