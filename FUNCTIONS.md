# MoneyWiz Command Reference

`moneywiz` is the configuration-aware dispatcher installed with MoneyWiz
Tools.app. It reads `db_path` from `~/.moneywizrc`; use an absolute path, or
override it per command with `--db PATH`.

## Global commands and options

| Command or option | Example | Purpose |
| --- | --- | --- |
| `--help`, `-h` | `moneywiz --help` | Show the current command syntax. |
| `--version`, `-V` | `moneywiz --version` | Show the installed bundle version without starting Python or opening a database. |
| `--setup` | `moneywiz --setup` | Create `~/.moneywizrc` when it does not exist. |
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
| `schema` | `moneywiz schema --out-md doc/DB-SCHEMA.md --out-json doc/schema.json` | Export schema documentation and JSON. |
| `shell` | `moneywiz shell` | Start the configuration-aware interactive API shell. |
| `compatibility` | `moneywiz compatibility --capability write.reassign-payees-by-id` | Show the detected profile and operation status. |

Use `moneywiz transactions --list-fields` to discover selectable transaction
fields. Use `--fields f1,f2` or `--all-fields` when a narrower or wider result
is needed.

## Retired raw-SQL commands

The following historical examples document former development helpers. They
are no longer exposed by the product command and must not be used as a live
write contract.

Create the test copy first:

~~~sh
moneywiz create-test-db
moneywiz sanitize-test-db
~~~

Then target it explicitly:

| Command | Example |
| --- | --- |
| `insert` | `moneywiz --db tests/test_db.sqlite insert --type Payee --fields '{"ZNAME5":"Example merchant"}' --apply` |
| `update` | `moneywiz --db tests/test_db.sqlite update --id 1234 --fields '{"ZNAME5":"Renamed merchant"}' --apply` |
| `delete` | `moneywiz --db tests/test_db.sqlite delete --id 1234 --apply` |
| `safe-delete` | `moneywiz --db tests/test_db.sqlite safe-delete --id 1234 --apply` |
| `rename` | `moneywiz --db tests/test_db.sqlite rename --id 1234 --name "Renamed merchant" --apply` |
| `assign-categories` | `moneywiz --db tests/test_db.sqlite assign-categories --tx 1234 --splits '[[42,18.19]]' --apply` |
| `assign-tags` | `moneywiz --db tests/test_db.sqlite assign-tags --tx 1234 --tags '[7,11]' --apply` |
| `link-refund` | `moneywiz --db tests/test_db.sqlite link-refund --refund 2001 --withdraw 1999 --apply` |

## Live payee operations

The following commands use the bundled Core Data host when `--apply` is
present and the detected profile marks that operation `verified`. Let
MoneyWiz finish syncing, quit the app, inspect the plan, then run the apply
command. Reopen MoneyWiz and confirm sync health afterwards.

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
normalized names.

### Merge exact duplicate payees

`merge-duplicate-payees` consolidates only duplicate names that are equal for
the same user after Unicode NFKC normalization, whitespace collapse, and case
folding. Similar names are review data only; the fuzzy CSV is never read to
perform a merge.

1. Create and inspect an exact-merge plan, and export similar-name candidates:

   ~~~sh
   moneywiz merge-duplicate-payees --show-plan \
     --fuzzy-map "$HOME/payee-fuzzy-review.csv"
   ~~~

2. Review the plan. The CSV may help identify future cleanup candidates, but
   changing it does not affect this command.

3. The CLI application capability is currently blocked pending separate
   acceptance evidence:

   ~~~sh
   moneywiz compatibility --capability write.merge-duplicate-payees
   ~~~

4. For an approved exact group, merge it in MoneyWiz 2026 through
   **Preferences > Payees > Edit**. Reopen the transaction form and confirm
   iCloud Sync is `Up to Date`.

Use `--quiet` on either live operation when only machine-readable output is
needed.

## Resolving fuzzy-review pending rows

`pending` means no reviewer has decided whether the two names identify the same
merchant. The CSV is audit metadata only: `merge-duplicate-payees --apply`
never reads or applies it.

| Decision | CSV fields to record | Next action |
| --- | --- | --- |
| Same merchant | `review_decision=approved`, `approved_canonical_id=<survivor ID>`, and `review_notes`. | Search both payees in **Preferences > Payees > Edit**, select them by ID, then merge and choose the recorded survivor. |
| Different merchants | `review_decision=rejected` and `review_notes`. | Keep both payees. |
| Insufficient evidence | Leave `review_decision=pending`; add a note if useful. | Take no write action. |

Do not expect a later `merge-duplicate-payees --apply` run to consume approved
rows.

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

The current CLI stops at this review artifact. Editing `approved` or
`rejected` does not trigger a write command. Use the CSV as an index for the
GUI workflow:

1. Search `left_name` and `right_name` in **Preferences > Payees > Edit**.
2. Use `left_id` and `right_id` to distinguish the records when names are
   similar or truncated.
3. Select the duplicate payees and invoke the GUI merge action, choosing the
   canonical survivor.
4. After the GUI merge succeeds, set `review_decision=approved`, record the
   survivor in `approved_canonical_id`, and add the rationale to
   `review_notes`. For a non-merge, record `rejected` and the reason instead.

The current CLI does not import these fields or execute the GUI merge from the
CSV.

## Command safety summary

| Database scope | Commands |
| --- | --- |
| Any configured store, read-only | `users`, `accounts`, `categories`, `payees`, `tags`, `transactions`, `holdings`, `record`, `summary`, `stats`, `schema`, `shell`, `compatibility` |
| Live iCloud store through Core Data | `reassign-payees-by-id --apply` when its profile capability is verified |
| Planned but blocked | `merge-duplicate-payees --apply` until independent acceptance evidence is recorded |

For the persistent-history and CloudKit contract, see
[Core Data Writer](doc/CORE-DATA-WRITER.md),
[Live Write Compatibility](doc/LIVE-WRITE-COMPATIBILITY.md), and
[Payee Consolidation](doc/PAYEE-CONSOLIDATION.md).
