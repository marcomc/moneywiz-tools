# Core Data Writer

## Purpose and current scope

The bundled Core Data writer is the live-store write path for
`reassign-payees-by-id --apply`. It exists because changing relationship
columns with raw SQLite does not create the Core Data persistent-history and
CloudKit metadata that MoneyWiz expects.

The current writer is verified for:

- Reassigning transactions to an existing payee.
- Creating a destination payee when reassignment requires one.
- Saving through the installed MoneyWiz Tools.app host.

It now implements exact-normalized duplicate consolidation using the same
host. The first live batch remains subject to the operational revalidation
described in [Payee Consolidation](PAYEE-CONSOLIDATION.md).

It is not a general live SQL writer and it never applies similar-name pairs
from the approval map.

## Operational protocol

```mermaid
flowchart LR
    accTitle: Live payee write protocol
    accDescr: Preview a reassignment or exact duplicate merge, stop MoneyWiz, use the bundled Core Data host to save, then reopen MoneyWiz and confirm iCloud sync completes.
    A["Preview the payee plan"] --> B["Quit MoneyWiz and allow sync to settle"]
    B --> C["Run the selected moneywiz payee command with --apply"]
    C --> D["Bundled Swift host opens the persistent store"]
    D --> E["Core Data saves object changes and persistent history"]
    E --> F["Reopen MoneyWiz"]
    F --> G["Confirm iCloud Sync is Up to Date"]
```

Do not run `--apply` while MoneyWiz has the database open. Do not use a
generic raw SQL helper as a substitute for this protocol.

## Host arrangement

The executable is inside the installed outer bundle:

```text
MoneyWiz Tools.app/Contents/MacOS/MoneyWizTools
```

It has bundle identity `com.marcomc.moneywiz-tools` and uses transaction
author `MWLocalAuthor`. The outer app bundle is the writer host; no separate
MoneyWizWriter.app is required.

The bundle also contains the Python dispatcher and scripts. The Swift host is
not a wrapper around an external development checkout.

## Verified compatibility profile

| Property | Observed value |
| --- | --- |
| Application | MoneyWiz 2026.32.1, build 431 |
| Managed-object model | MoneyWizDataModel 48 |
| Payee entity in live profile | `Z_ENT = 29` |
| Root transaction entities | `Z_ENT = 37` through `48` |
| Persistent-history writer | Core Data through the bundled host |

These values are evidence for the observed profile, not a permanent schema
guarantee. Revalidate after an app or model migration.

## Behavior at duplicate names

The reassignment planner normalizes names before selecting a destination. It
fails when more than one matching candidate remains, preventing accidental
selection of a duplicate. Existing and new destination creation are supported.

`merge-duplicate-payees` performs the separate exact-normalized merge
operation. It migrates all model relationships whose destination is `Payee`,
validates that the source has no remaining supported reference, and deletes
the source in the same Core Data save. Similar-name pairs stay pending in an
approval CSV.

See [Live Payee Structure](LIVE-PAYEE-STRUCTURE.md) for the recorded live
mappings and [Live Write Compatibility](LIVE-WRITE-COMPATIBILITY.md) for the
full operating and revalidation contract.
