# Functions Reference

This reference distinguishes the installed dispatcher from the separate
upstream API shell.

## Entrypoints

| Command | Role | Database selection |
| --- | --- | --- |
| `moneywiz` | Installed MoneyWiz Tools dispatcher. Reads, test-copy helpers, and the verified live reassignment command. | `~/.moneywizrc`, or global `--db`. |
| `moneywiz.sh` | Source-tree form of the dispatcher for development. | Same launcher configuration rules. |
| `moneywiz-cli` | Read-only interactive API shell from `moneywiz-api`. | Explicit positional database path only. |

Use `moneywiz --help` for the current command syntax. The dispatcher help is
the source of truth when a documented example and installed command disagree.

## Read operations

The dispatcher provides read-only commands for:

- Users
- Accounts
- Categories
- Payees
- Tags
- Transactions
- Holdings
- Schema and record inspection
- Summary and statistics

Examples:

~~~sh
moneywiz payees
moneywiz transactions
moneywiz record 1234
moneywiz summary
~~~

## Write operations

The dispatcher exposes generic write helpers for test copies and a narrowly
verified writer for the live store.

| Operation family | Intended database |
| --- | --- |
| Insert, update, delete, safe-delete, rename, category, tag, and refund helpers | Test copy or disposable database. |
| `reassign-payees-by-id --apply` | Live store after the operational protocol is followed. |
| `merge-duplicate-payees --apply` | Exact-normalized duplicate groups through the Core Data host. |

The live reassignment command runs through the bundled Core Data host. It can
reuse a destination payee or create one from a transaction description. It
stops on ambiguous normalized payee names.

`merge-duplicate-payees` handles those exact duplicate groups separately. It
uses NFKC, whitespace collapse, and case folding; chooses a readable canonical
name deterministically; and emits similar-only pairs to an approval CSV. It
never applies the fuzzy CSV.

## Interactive API shell

Start the API shell with a real path:

~~~sh
moneywiz-cli /absolute/path/to/MoneyWiz_iCloud.sqlite
~~~

The shell is read-only and does not load `~/.moneywizrc`. `moneywiz-cli
payees` is invalid because the first argument is reserved for the database
path.

## Database selection

For `moneywiz`, configure an absolute path in `~/.moneywizrc`:

~~~ini
db_path=/absolute/path/to/MoneyWiz_iCloud.sqlite
~~~

Do not use `~` in that value. Override it per invocation with global `--db`:

~~~sh
moneywiz --db /absolute/path/to/store.sqlite payees
~~~
