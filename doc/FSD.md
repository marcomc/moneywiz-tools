# Functional Specification

## Product purpose

MoneyWiz Tools provides local command-line access to a MoneyWiz SQLite store.
It separates routine inspection from typed, guarded live write operations.

## User-facing entrypoints

| Entrypoint | Intended use |
| --- | --- |
| `moneywiz` | Main installed dispatcher. |
| `moneywiz.sh` | Development-tree dispatcher. |

## Functional scope

### Read operations

The main dispatcher lists and inspects users, accounts, categories, payees,
tags, transactions, holdings, records, summaries, statistics, and schema.

### Live payee operations

`reassign-payees-by-id --apply` is the current verified live writer for a
matching profile. It plans the change, refuses ambiguous normalized targets,
and uses the bundled Core Data host to reuse or create a destination payee.

`merge-duplicate-payees` plans exact-normalized groups and exports similar-name
pairs for manual review; its legacy apply path remains blocked. W09
`payee merge` plans one exact or explicitly approved fuzzy pair using the complete
native reference inventory, and `write apply` executes the reviewed plan.

Version-2 plans also implement the finite W01–W08 transaction operations. See
[Live Write Compatibility](LIVE-WRITE-COMPATIBILITY.md) for exact runtime, account
and acceptance boundaries.

### Explicit exclusions

- No generic raw-SQL product writer.
- No unapproved similar-name duplicate merge.
- No GUI yet.
- No claim that test-store entity numbers describe every live model.

## Acceptance criteria

- `make install` creates or refreshes the app bundle and installs `moneywiz`.
- Installed commands run without a development repository path.
- Reassignment preview requires no live write.
- A verified live reassignment completes through Core Data only after the app
  has released the store and is followed by a successful app sync.
