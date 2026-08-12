# Live Write Compatibility

## Current status

MoneyWiz Tools intentionally supports direct work with the live database, but
compatibility is defined per write path.

| Operation | Current status | Required path |
| --- | --- | --- |
| Inspect the live store | Supported | Read-only SQLite access. |
| Generic SQL mutation | Not a product capability | Do not infer iCloud compatibility from SQL success. |
| Reassign a payee to an existing destination | Verified | Bundled Core Data writer. |
| Reassign a payee and create its destination | Verified | Bundled Core Data writer. |
| Merge exact-normalized duplicate payees | Blocked | Requires independent Core Data acceptance evidence. |
| Merge similar-name payees | Not implemented | Requires an approved map and a separate reviewed contract. |

No backup requirement is imposed by the command. The operator remains
responsible for deciding their own recovery posture before modifying
financial data.

## Operating rule

Use the reassignment planner first:

~~~sh
moneywiz reassign-payees-by-id --from-payee-id 1234 --show-plan
~~~

Review the result. If the plan is correct:

1. Let MoneyWiz complete any active sync.
2. Quit MoneyWiz so it releases the persistent store.
3. Run the same command with `--apply`.
4. Reopen MoneyWiz.
5. Confirm iCloud Sync reports **Up to Date**.

The tool refuses ambiguous normalized payee names. Resolve or consolidate those
duplicates through the MoneyWiz GUI while
`write.merge-duplicate-payees` remains blocked. Export similar pairs with
`--fuzzy-map PATH`; they remain pending until an explicitly approved workflow
exists.

## Compatibility profile

The verified writer was observed with MoneyWiz 2026.32.1, build 431, using
managed-object model `MoneyWizDataModel 48`. The runtime register calls this
`moneywiz-2026-model-48`. The current live store places payees and
transaction subclasses in Core Data storage with shared `ZSYNCOBJECT`
identity and version fields.

The relevant payee relationships are documented in
[Live Payee Structure](LIVE-PAYEE-STRUCTURE.md). The writer itself is
documented in [Core Data Writer](CORE-DATA-WRITER.md).

## Evidence for the current path

The current host was tested against the live profile by:

- Reassigning to an existing payee.
- Reassigning while creating a new destination payee.
- Reopening MoneyWiz after each operation.
- Confirming the app consumed persistent history and iCloud export advanced.
- Confirming the app reported a successful sync.

This proves reassignment for the observed profile. It does not prove that an
arbitrary column-level SQL update, other app versions, or a duplicate merge has
the same compatibility. Exact duplicate consolidation needs its own acceptance
evidence despite using the same host.

## Historical finding

The earlier raw reassignment updated only visible relationship data. It did
not reproduce the object lifecycle expected by Core Data, persistent history,
and CloudKit. MoneyWiz later crashed when creating a transaction, which is
why the live reassignment implementation now saves through Core Data.

Treat this as an implementation lesson, not as a prohibition on all direct
database work: read access and verified writer paths remain useful. The
boundary is between a reconstructed live object contract and an untracked raw
mutation.

## Revalidation triggers

Re-run a minimal existing-payee and new-payee reassignment test when any of
these change:

- MoneyWiz application version or managed-object model.
- Database location, account, or sync provider.
- Core Data host bundle identity or transaction author.
- The fields or relationships touched by the writer.

Keep the scope minimal, wait for sync completion, and restore any test
transactions created solely for the test.

## Runtime enforcement

Run `moneywiz compatibility` to inspect the detected profile and
`moneywiz compatibility --capability NAME` before applying a write. The
Python preflight passes both the profile ID and writer-contract version to the
Swift host. An unknown profile or any capability other than `verified` fails
before opening the persistent store.
