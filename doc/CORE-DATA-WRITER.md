# Core Data Writer

## Purpose and current scope

The bundled Core Data writer is the live-store write path for product
operations that have a verified capability. It exists because changing relationship
columns with raw SQLite does not create the Core Data persistent-history and
CloudKit metadata that MoneyWiz expects.

The current writer implements and is verified for:

- Reassigning transactions to an existing payee.
- Creating a destination payee when reassignment requires one.
- Saving through the installed MoneyWiz Tools.app host.

The Python CLI can plan exact-normalized duplicate consolidation, but the
native host does not implement relationship migration or source-payee deletion.
The corresponding capability remains blocked. Verification is
operation-specific.

It is not a general live SQL writer and it never applies similar-name pairs
from the approval map.

## Operational protocol

```mermaid
flowchart LR
    accTitle: Live payee write protocol
    accDescr: Verify the profile capability, preview the plan, stop MoneyWiz, use the bundled Core Data host to save, then reopen MoneyWiz and confirm iCloud sync completes.
    A["Check profile capability and preview the payee plan"] --> B["Quit MoneyWiz and allow sync to settle"]
    B --> C["Run the selected moneywiz payee command with --apply"]
    C --> D["Bundled Swift host opens the persistent store"]
    D --> E["Core Data saves object changes and persistent history"]
    E --> F["Reopen MoneyWiz"]
    F --> G["Confirm iCloud Sync is Up to Date"]
```

Do not run `--apply` while MoneyWiz has the database open. The Python preflight
requires `pgrep` to confirm that the MoneyWiz process is stopped, and the Swift
host independently checks both known MoneyWiz bundle identifiers before it
reads store metadata. Inspection failures stop the write. These checks are not
an atomic exclusion lock, so keep MoneyWiz closed until the command finishes.
Do not use a generic raw SQL helper as a substitute for this protocol.

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
| Application | MoneyWiz 2026.32.1, builds 431 and 433 |
| Managed-object model | MoneyWizDataModel 48 |
| Exact model checksum | `+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ=` |
| Payee entity in live profile | `Z_ENT = 29` |
| Root transaction entities | `Z_ENT = 37` through `48` |
| Persistent-history writer | Core Data through the bundled host |

These values are evidence for the observed profile, not a permanent schema
guarantee. Revalidate after an app or model migration.

The runtime register in `scripts/compatibility_matrix.json` identifies this
profile as `moneywiz-2026-model-48`. It allows
`write.reassign-payees-by-id` and blocks
`write.merge-duplicate-payees` before the host is launched.

The Python preflight and Swift host both enforce the exact model checksum. The
Python payload also binds the verified capability. Before it opens the
persistent store, the host requires the exact profile ID, checksum,
`write.reassign-payees-by-id` capability, schema version 1, and a non-empty
reassignment-only operation list. Schema 2, merge, mixed, blocked, and unknown
capability payloads fail closed.

The default model resolver reads the current-version leaf from the installed
`MoneyWizDataModel.momd` manifest. It accepts the observed extensionless form
by appending `.mom` once, or uses an existing `.mom` suffix literally; unsafe
paths, unsupported suffixes, and missing model files fail closed.

The planner classifies every selected transaction as either one writer
operation or an explicit no-op. A missing or dangling account or owner, a
missing transaction GID, or an empty description without a configured fallback
rejects the entire plan. The summary reports selected, updated, and no-op
counts so `selected = updated + no-ops` is always visible.
Account references must resolve to the verified `Account` Core Data entity
family; an arbitrary `ZSYNCOBJECT` row with an owner field is not accepted as
an account.

The host admits only the ten transaction entities used by the Python planner:
`DepositTransaction`, `InvestmentExchangeTransaction`,
`InvestmentBuyTransaction`, `InvestmentSellTransaction`,
`ReconcileTransaction`, `RefundTransaction`, `TransferBudgetTransaction`,
`TransferDepositTransaction`, `TransferWithdrawTransaction`, and
`WithdrawTransaction`. It rejects parent, sibling, payee, user, and arbitrary
entity names even when a supplied GID exists elsewhere in the model.

Before any insert or relationship assignment, the host validates the complete
payload and resolves every transaction by exact entity and GID, every account
owner, every existing payee owner, and every shared new-payee key. Duplicate
transaction GIDs, partial or mixed targets, inconsistent key-to-name mappings,
and keys spanning users stop the write before mutation. Only after this
read-only preflight succeeds does one mutation phase create payees, assign
relationships, and save.

## Behavior at duplicate names

The reassignment planner normalizes names before selecting a destination. It
fails when more than one matching candidate remains, preventing accidental
selection of a duplicate. Existing and new destination creation are supported.
When multiple descriptions share one user-scoped normalized creation key, the
lowest selected transaction ID supplies one deterministic display name for the
entire group.

`merge-duplicate-payees` has a separate exact-normalized Python plan. Its
application remains unavailable: the capability gate rejects `--apply`, and
the native host has no merge mutation route. Similar-name pairs stay pending
in an approval CSV.

See [Live Payee Structure](LIVE-PAYEE-STRUCTURE.md) for the recorded live
mappings and [Live Write Compatibility](LIVE-WRITE-COMPATIBILITY.md) for the
full operating and revalidation contract.
