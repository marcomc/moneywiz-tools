# MoneyWiz Command Reference

`moneywiz` is the configuration-aware dispatcher installed with MoneyWiz
Tools.app. It reads `db_path` from `~/.moneywizrc`; use an absolute path, one
beginning with `~/`, or override it per command with `--db PATH`.

Run `moneywiz --help` for the executable's current top-level syntax. This page
is the task-oriented reference for the same interface; command-specific help
is authoritative when an option or default changes.

| Dispatcher | Where it runs | Intended audience |
| --- | --- | --- |
| `moneywiz` | Installed app bundle via `~/.local/bin/moneywiz` | End users and automation |
| `./moneywiz.sh` | Source checkout | Developers and fixture maintenance |

The installed command is self-contained. It does not depend on this checkout,
system Python, `pyenv`, or `uv` at runtime.

## Global commands and options

| Command or option | Example | Purpose |
| --- | --- | --- |
| `--help`, `-h` | `moneywiz --help` | Show the current command syntax. |
| `--version`, `-V` | `moneywiz --version` | Show the installed bundle version without starting Python or opening a database. |
| `--setup` | `moneywiz --setup` | Create `~/.moneywizrc` when it does not exist, preferring the current MoneyWiz 2026 store and falling back to the legacy store. |
| `--db PATH` | `moneywiz --db /absolute/path/store.sqlite payees` | Override `db_path` for one invocation. |

`moneywiz` is the only supported end-user command.

## Read commands

All read commands accept `--format table|json` unless their own help says
otherwise.

| Command | Example | Purpose |
| --- | --- | --- |
| `users` | `moneywiz users` | List MoneyWiz users. |
| `accounts` | `moneywiz accounts --user 1` | List accounts, optionally for one user. |
| `categories` | `moneywiz categories --user 1 --full-name` | List categories with their hierarchy. |
| `payees` | `moneywiz payees --user 1 --sort-by-name` | List payees and optionally sort by name. |
| `tags` | `moneywiz tags --user 1` | List tags. |
| `transactions` | `moneywiz transactions --account 42 --until 2026-08-01 --limit 100 --with-categories --with-tags` | List account transactions. |
| `holdings` | `moneywiz holdings --account 42` | List investment holdings for an account. |
| `record` | `moneywiz record --id 1234` | Inspect a record by numeric ID. |
| `record` | `moneywiz record --gid A1B2C3D4-...` | Inspect a record by global ID. |
| `summary` | `moneywiz summary` | Print a database summary. |
| `stats` | `moneywiz stats --out "$HOME/moneywiz-stats"` | Write statistics reports to a directory. |
| `schema` | `moneywiz schema` | Export schema documentation and JSON under `${XDG_DATA_HOME:-$HOME/.local/share}/moneywiz-tools/schema`; use `--out-md` and `--out-json` for explicit destinations. |
| `shell` | `moneywiz shell` | Start the configuration-aware interactive API shell. |
| `compatibility` | `moneywiz compatibility --capability write.reassign-payees-by-id` | Show the detected profile and operation status. |
| `identity` | `moneywiz identity --app /Applications/MoneyWiz.app` | Read app/store/owner identity and verify the selected compiled model checksum. |
| `snapshot` | `moneywiz snapshot --account 10 --until 2026-09-12 --timezone Europe/Rome` | Export JSON completeness, relationships, flags and bounded graph diagnostics. |

Use `moneywiz transactions --list-fields` to discover selectable transaction
fields. Use `--fields f1,f2` or `--all-fields` when a narrower or wider result
is needed.

All commands accept `--help` without opening the configured database. For a
machine-readable result, pass `--format json` to commands that advertise the
`table|json` format. `record`, `summary`, and the interactive shell retain
their command-specific output behavior.

## Versioned writer and recovery

The version-2 interface accepts a saved typed plan and defaults to inspection.
W01 creation, W02 editing, W03 assignment and W04 reconciliation are enabled
on the reviewed live Setapp runtime and marked disposable model-48 fixtures. See
[Transaction Creation](doc/TRANSACTION-CREATION.md) for creation fields,
[Transaction Editing](doc/TRANSACTION-EDITING.md) for edit fields,
[Transaction Assignment](doc/TRANSACTION-ASSIGNMENT.md) for relationships,
[Transaction Reconciliation](doc/TRANSACTION-RECONCILIATION.md) for flags, and
[Transaction Adjust Balance](doc/TRANSACTION-ADJUST-BALANCE.md) for ordinary
balance, investment cash, existing-asset quantity and the observed investment-total
variant. W05 investment-total creation supports the reviewed fiat/crypto
currency catalogs for accounts without holdings, with explicit native precision
and reporting rates; original GBP plans and the exact TestFlight 2026.37.1
build 449 live path are preserved. W06 deletion is enabled on the reviewed
live Setapp runtime and marked disposable stores. See
[Writer Recovery](doc/WRITER-RECOVERY.md) for journals.
W07 transfer replacement is enabled on the reviewed live Setapp runtime and
marked disposable stores; see
[Transaction Transfer](doc/TRANSACTION-TRANSFER.md) for its paired-leg contract.
W08 investment cash events, existing-holding Buy/Sell and first Buy creating a
manual investment holding are enabled on the reviewed live Setapp runtime and
marked disposable stores; see [Investment Transactions](doc/TRANSACTION-INVESTMENT.md).
W09 payee merges use one reviewed source/survivor pair and a complete native
reference inventory; see [Payee Consolidation](doc/PAYEE-CONSOLIDATION.md).

| Command | Behavior |
| --- | --- |
| `transaction create --request FILE --plan FILE` | Build a W01 plan from explicit JSON inputs without opening a store |
| `transaction edit --request FILE --plan FILE` | Build a guarded W02 scalar edit plan without opening a store |
| `transaction assign --request FILE --plan FILE` | Build a guarded W03 payee/category replacement plan without opening a store |
| `transaction reconcile --request FILE --plan FILE` | Build a guarded W04 reconciliation plan without opening a store |
| `transaction unreconcile --request FILE --plan FILE` | Build a guarded W04 correction plan without opening a store |
| `transaction adjust-balance --request FILE --plan FILE` | Build an explicit W05 ordinary balance, investment cash, existing-asset quantity or currency-aware investment-total plan without opening a store |
| `transaction delete-adjustment --request FILE --plan FILE` | Build a W06 plan for one exact latest investment-total adjustment without opening a store |
| `transaction delete --target GID --reason TEXT --evidence-note TEXT --plan FILE` | Build a W06 plan from a native read-only inventory; repeat `--target` for complete transfer/refund groups; see [Supported Transaction Deletion](doc/TRANSACTION-DELETION.md) for status |
| `transaction transfer --request FILE --plan FILE` | Build a W07 plan to replace one or two imported rows with a zero-fee paired transfer without opening a store |
| `transaction investment --request FILE --plan FILE` | Build one guarded W08 cash event, existing-holding Buy/Sell or first-Buy holding plan without opening a store |
| `payee merge --kind KIND --source-gid GID --survivor-gid GID --plan FILE` | Build one W09 merge plan from a native read-only inventory; fuzzy requires `--fuzzy-map` |
| `write validate --plan FILE` | Validate and display the exact plan and canonical digest |
| `write apply --plan FILE` | Inspect without mutation |
| `write apply --plan FILE --reviewed-digest SHA --apply` | Apply the reviewed coherent unit with durable recovery evidence |
| `write recover --plan FILE` | Inspect persisted state without replaying an unknown outcome |
| `write locations` | Discover private artifact paths, provenance and retention |
| `write journal` | List durable execution states |
| `write cleanup` | Preview eligible evidence and space |
| `write cleanup --apply` | Recheck eligibility and prune only expired verified evidence |

Apply and recover also accept `--app`, `--model` and `--owner`; the global
`--db` option selects the store. Runtime selection must match the reviewed plan.

## Retired raw-SQL commands

Earlier releases exposed `insert`, `update`, `delete`, `safe-delete`, `rename`,
`assign-categories`, `assign-tags`, and `link-refund`. The current product and
source-tree dispatchers do not route those commands. Their old syntax is not a
supported test or live-write interface.

The source checkout provides the test-database lifecycle commands:

~~~sh
./moneywiz.sh create-test-db
./moneywiz.sh sanitize-test-db
~~~

These commands create and sanitize a disposable copy; they do not restore the
retired raw-SQL routes. `create-test-db` reads from `--db PATH`, then configured
`db_path`, then the same current-before-legacy store discovery as `--setup`.
It copies that source into `tests/test_db.sqlite` without modifying the source,
including when the source is a live store. The generated fixture must be
disposable; `sanitize-test-db` operates only on that fixture. These commands
are not present in the installed bundle.

## Live payee operations

Live reassignment uses the bundled Core Data host when `--apply` is present and
the detected profile marks that operation `verified`. Let MoneyWiz finish
syncing, quit the app, inspect the plan, then run the apply command. Reopen
MoneyWiz and confirm sync health afterwards. Duplicate-merge planning is
read-only; its apply capability is blocked.

### Reassign payees by transaction description

Preview reassignment for one source payee:

~~~sh
moneywiz reassign-payees-by-id --from-payee-id 9036 --show-plan
~~~

Apply the reviewed plan after quitting MoneyWiz:

~~~sh
moneywiz reassign-payees-by-id --from-payee-id 9036 --apply
~~~

Confirm the gate before applying:

~~~sh
moneywiz compatibility --capability write.reassign-payees-by-id
~~~

Other supported selectors:

~~~sh
moneywiz reassign-payees-by-id --from-empty-payee --show-plan
moneywiz reassign-payees-by-id --from-empty-payee \
  --empty-desc-target-payee-id 8703 --apply
~~~

The command reuses a uniquely matching payee or creates one from the
transaction description. It stops instead of choosing among ambiguous
normalized names. When several selected descriptions normalize to the same
new-payee key, the lowest transaction ID supplies one display name for every
operation in that user-scoped group.

### Merge exact duplicate payees

`merge-duplicate-payees` plans duplicate names that are equal for the same user
after Unicode NFKC normalization, whitespace collapse, and case folding.
Similar names are review data only; the fuzzy CSV is never read to perform a
merge through this legacy group command. Its `--apply` path is rejected by the
blocked capability gate. The separate `payee merge` command accepts one
explicit source/survivor pair and reads an approved fuzzy CSV row when asked.

1. Create and inspect an exact-merge plan:

   ~~~sh
   moneywiz merge-duplicate-payees --show-plan
   ~~~

2. When a similar-name review is needed, request the separate fuzzy analysis
   and CSV export explicitly:

   ~~~sh
   moneywiz merge-duplicate-payees \
     --fuzzy-map "$HOME/payee-fuzzy-review.csv"
   ~~~

   Exact-only dry runs and legacy apply attempts do not perform the quadratic fuzzy
   comparison pass.

3. Review the plan. Editing the CSV does not affect this legacy command; an
   approved row can be supplied explicitly to `payee merge --kind fuzzy`.

4. The legacy group application capability remains blocked:

   ~~~sh
   moneywiz compatibility --capability write.merge-duplicate-payees
   ~~~

5. For an approved exact group, merge it in MoneyWiz 2026 through
   **Preferences > Payees > Edit**. Reopen the transaction form and confirm
   iCloud Sync is `Up to Date`.

Use `--quiet` on the legacy group or reassignment command when only
machine-readable output is needed.

## Resolving fuzzy-review pending rows

`pending` means no reviewer has decided whether the two names identify the same
merchant. `merge-duplicate-payees --apply` never reads or applies the CSV;
`payee merge --kind fuzzy` reads one matching approved row. Names beginning
with `=`, `+`, `-`, or `@` are
prefixed with an apostrophe in the export so spreadsheet applications treat
them as literal text. Detection also covers compatibility-equivalent sigils and
sigils hidden behind leading Unicode whitespace or control characters; the
original name is otherwise preserved character-for-character.

| Decision | CSV fields to record | Next action |
| --- | --- | --- |
| Same merchant | `review_decision=approved`, `approved_canonical_id=<survivor ID>`, and `review_notes`. | Build and review one W09 fuzzy pair plan, then apply it through the enabled native path. |
| Different merchants | `review_decision=rejected` and `review_notes`. | Keep both payees. |
| Insufficient evidence | Leave `review_decision=pending`; add a note if useful. | Take no write action. |

Do not expect a later `merge-duplicate-payees --apply` run to consume approved
rows. Use [Payee Consolidation](doc/PAYEE-CONSOLIDATION.md) for the reviewed live
or disposable W09 plan and reviewed-digest apply path.

### How to edit the CSV

Do not add a second row and do not change the merchant IDs or names. Edit the
review columns of the existing row:

~~~csv
user_id,similarity,reason,left_id,left_name,right_id,right_name,review_decision,approved_canonical_id,review_notes
1,0.919,similarity>=0.88,1037,Merchant Example A,1892,Merchant Example B,pending,,
~~~

If both IDs are the same merchant and `1037` should survive, edit only the
review fields like this:

~~~csv
1,0.919,similarity>=0.88,1037,Merchant Example A,1892,Merchant Example B,approved,1037,"Same merchant; keep the readable canonical payee."
~~~

If they are different merchants, leave `approved_canonical_id` empty:

~~~csv
1,0.919,similarity>=0.88,1037,Merchant Example A,1892,Merchant Example B,rejected,,"Different merchants despite similar names."
~~~

Editing `approved` or `rejected` does not trigger a write. To apply an approved
row through the CLI, build one `payee merge --kind fuzzy` plan with the CSV and
explicit source/survivor GIDs, then review and apply its digest as documented in
[Payee Consolidation](doc/PAYEE-CONSOLIDATION.md). For a GUI merge, use the CSV
as an index:

1. Search `left_name` and `right_name` in **Preferences > Payees > Edit**.
2. Use `left_id` and `right_id` to distinguish the records when names are
   similar or truncated.
3. Select the duplicate payees and invoke the GUI merge action, choosing the
   canonical survivor.
4. After the GUI merge succeeds, set `review_decision=approved`, record the
   survivor in `approved_canonical_id`, and add the rationale to
   `review_notes`. For a non-merge, record `rejected` and the reason instead.

The legacy `merge-duplicate-payees` command does not consume review fields.
The separate W09 `payee merge --kind fuzzy` path validates one approved row;
pending and rejected rows remain no-ops.

## Command safety summary

| Database scope | Commands |
| --- | --- |
| Configured or explicitly selected store, read-only | `users`, `accounts`, `categories`, `payees`, `tags`, `transactions`, `holdings`, `snapshot`, `identity`, `record`, `summary`, `stats`, `schema`, `shell`, `compatibility` |
| Live iCloud store through Core Data | `reassign-payees-by-id --apply` when its profile capability is verified |
| Planning only; apply blocked | Legacy `merge-duplicate-payees --apply` remains unavailable |
| Reviewed live Setapp runtime or marked disposable model-48 store | `write apply` executes reviewed W01–W09 plans, including one explicit W09 payee pair; exact runtime and operation guards apply |

For the persistent-history and CloudKit contract, see
[Core Data Writer](doc/CORE-DATA-WRITER.md),
[Live Write Compatibility](doc/LIVE-WRITE-COMPATIBILITY.md), and
[Payee Consolidation](doc/PAYEE-CONSOLIDATION.md).
