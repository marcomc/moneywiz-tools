# Live Write Compatibility

## Contents

- [Purpose](#purpose)
- [Observed schema profile](#observed-schema-profile)
- [Confirmed persistence contract](#confirmed-persistence-contract)
- [Reassignment gap](#reassignment-gap)
- [Versioning and maintenance](#versioning-and-maintenance)
- [Next discovery capture](#next-discovery-capture)

## Purpose

This document records what a direct SQL writer must preserve when editing the
live MoneyWiz iCloud store. It is separate from `DB-SCHEMA.md`, which is a
generated snapshot of `tests/test_db.sqlite`.

The observations below are evidence, not a complete implementation recipe.
Do not infer undocumented Core Data or CloudKit values from them.

## Observed schema profile

| Field | Value |
| --- | --- |
| Observed on | 2026-08-08 |
| MoneyWiz version | 2026.32.1 |
| MoneyWiz build | 431 |
| Store | `MoneyWiz_iCloud.sqlite` |
| `Z_METADATA.Z_VERSION` | `1` |
| `Z_METADATA.Z_PLIST` SHA-256 | `0b3d88200511cb08f63414e63f8ec07e700485df53c7cf6060329458dcfad71e` |

`Z_METADATA.Z_VERSION` is the Core Data metadata-row version, not the
MoneyWiz application or model version. `Z_METADATA.Z_UUID` identifies one
physical store and must not be used to generalize a schema rule. The
`Z_PLIST` fingerprint is the versioning key for this compatibility profile.

## Confirmed persistence contract

| Concern | Observed tables | Status |
| --- | --- | --- |
| Domain row and optimistic version | `ZSYNCOBJECT` (`Z_OPT`) | Confirmed |
| Persistent history transaction | `ATRANSACTION` | Confirmed |
| Persistent history change | `ACHANGE` (`ZENTITY`, `ZENTITYPK`, `ZTRANSACTIONID`, `ZCOLUMNS`) | Confirmed |
| CloudKit record identity and upload state | `ANSCKRECORDMETADATA` | Confirmed |
| CloudKit history/export analysis | `ANSCKHISTORYANALYZERSTATE`, `ANSCKEXPORTMETADATA`, `ANSCKEXPORTEDOBJECT` | Present; exact write sequence pending capture |

The observed store contains a metadata row for every current Payee and the
relevant transaction types. Application-originated changes create
`ATRANSACTION` and `ACHANGE` records. `ACHANGE.ZCOLUMNS` is an opaque bitmap;
its value must be captured from an equivalent native MoneyWiz edit, not
guessed from a column name.

## Reassignment gap

The original `reassign-payees-by-id` apply path performed only these SQL
operations:

- Inserted a minimal Payee row in `ZSYNCOBJECT` when no matching payee existed.
- Updated `ZSYNCOBJECT.ZPAYEE2` on the matching transaction.

That omitted at least the following observed invariants:

- Incrementing the target row's `Z_OPT`.
- Creating an `ATRANSACTION` record for the mutation.
- Creating an `ACHANGE` record tied to that transaction with the correct
  `ZCOLUMNS` bitmap.
- Creating or updating CloudKit metadata for a new Payee and for the changed
  transaction.

A SQLite `BEGIN`/`COMMIT` makes those statements atomic, but does not create a
Core Data persistent-history transaction or CloudKit export state.

## Versioning and maintenance

Every live-write observation must record all of the following:

1. MoneyWiz marketing version and build.
2. `Z_METADATA.Z_PLIST` SHA-256 fingerprint.
3. The tested mutation and the pre/post table delta.
4. Whether the app and iCloud sync both accepted the result.

When either the app build or model fingerprint changes, mark the previous
profile as `needs revalidation`. Mark it `obsolete since <profile>` only after
a native pre/post capture demonstrates an incompatible delta.

## Next discovery capture

Two native MoneyWiz edits are required before implementing a live-compatible
reassignment writer:

1. Change one transaction from one existing payee to another existing payee.
2. Create a new payee in MoneyWiz and assign it to one transaction.

For each edit, capture a consistent SQLite backup before and after the save,
then compare `ZSYNCOBJECT`, `ATRANSACTION`, `ACHANGE`,
`ANSCKRECORDMETADATA`, and the `ANSCK*` export/history tables. The resulting
delta is the regression fixture for the direct writer.
