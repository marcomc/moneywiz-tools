# Further captured behaviour (MoneyWiz 2026.32.1 / build 431)

## Payee matching is Unicode-sensitive in storage

The application can store a visually ordinary payee name with non-breaking
spaces (`U+00A0`) while a transaction description contains ordinary spaces.
For example, the existing payee `Vodafone\u{00A0}Pag\u{00A0}Ricar\u{00A0}Au`
and its transaction description `Vodafone Pag Ricar Au` are visually the same
but are not byte-for-byte equal. An exact string match would incorrectly create
a duplicate payee.

Resolve an existing payee within the same user by comparing a canonical match
key: Unicode NFKC normalisation, whitespace collapse, and case folding. Retain
the application's stored spelling when assigning or presenting the payee.

## Native reassignment contract observed twice

For existing payees, the native app changed the transaction `ZPAYEE2`, advanced
the transaction `Z_OPT`, inserted one `ATRANSACTION` row, and inserted an
`ACHANGE` row with `ZCHANGETYPE = 1`, the transaction entity and PK, and
`ZCOLUMNS = 2000400100`. The transaction's `ANSCKRECORDMETADATA` row advanced
its `Z_OPT` and set `ZLASTEXPORTEDTRANSACTIONNUMBER` to the history transaction
number; the encoded record asset binary data changed as well.

One first sample also changed `ZNUMBEROFSHARES` from `0.0` to `NULL`. A second
sample did not. This is therefore an observed record-specific side effect, not
an update to reproduce generically.

## Native new-payee creation contract

The app created a new Payee with a lowercase, 32-character hexadecimal `ZGID`,
an app-normalised name containing non-breaking spaces, an object creation date,
and a non-null `ZIMPORTLINKIDARRAY2` binary property. It also created a Payee
`ACHANGE` insert row and matching `ANSCKRECORDMETADATA` / encoded-record asset
rows before linking the transaction through the reassignment change. The
Payee's `Z_PRIMARYKEY.Z_MAX` stayed `0`; it is not a valid allocator for this
database generation.

The binary import-link and encoded-record fields remain opaque. Do not copy
their values from another payee or manufacture placeholder blobs.

## Core Data prototype is insufficient alone

Loading the installed MoneyWiz Core Data model and saving an existing-payee
assignment on a copied SQLite store correctly updated `ZPAYEE2`, incremented
`Z_OPT`, and created persistent-history rows. It did not update
`ANSCKRECORDMETADATA` or encoded CloudKit record assets. Its generated
`ACHANGE` column bitmap was `2000000000`, rather than the native
`2000400100`, and its history author fields were empty.

This establishes that a plain external `NSPersistentStoreCoordinator` is not a
live-compatible writer. It may be useful for local structure experiments only;
the production reassignment path must reproduce the complete native persistence
and CloudKit metadata contract.

## Live Write Compatibility

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

## Encoded CloudKit asset format

The `ANSCKRECORDMETADATAENCODEDRECORDASSET.ZBINARYDATA` payload begins with a
`bvx*` wrapper and contains a `bplist00`-like keyed-archive representation. It
is not accepted by `plistlib`, `plutil`, or `NSKeyedUnarchiver` as a standalone
public archive. The native reassignment changes this payload, including its
length and internal object table.

Treat the payload as Core Data / CloudKit private serialization. A Python or
plain Core Data writer must not attempt to patch it, reuse another record's
asset, or synthesize it from observed bytes. A safe direct writer needs an
Apple-supported persistence path that updates this metadata as part of the
same save, or further evidence of a supported reconciliation mechanism.

## Falsification: raw payee writes remain locally usable

Two live, reversible tests against MoneyWiz 2026.32.1 falsified the earlier
assumption that every raw payee mutation must create Core Data history and
CloudKit artifacts before the app can safely use the database:

- A transaction was reassigned raw from an existing payee to another existing
  payee, MoneyWiz was restarted, and the app displayed and edited the changed
  transaction normally. Saving the original payee through the app regenerated
  native history, metadata, and the encoded asset.
- A minimal raw Payee was inserted with entity 29, a global `ZSYNCOBJECT` PK,
  lowercase 32-character hexadecimal `ZGID`, name, user, and creation date.
  It had no import-link blob, persistent history, CloudKit metadata, or encoded
  asset. A transaction assigned raw to this payee loaded and opened normally;
  the app then restored the original payee without crashing.

During the native restoration, MoneyWiz reconciled the temporary raw Payee: it
advanced its `Z_OPT`, created `ANSCKRECORDMETADATA` and an encoded asset, and
recorded an `ACHANGE` row. The temporary payee was subsequently deleted through
MoneyWiz's own Payees UI; the transaction stayed restored.

Therefore the observed Core Data / CloudKit rows describe the app's canonical
write and sync path, but are not proven required for an immediate local direct
payee write. The likely prior failure is narrower: incompatible raw object
creation, especially identity / primary-key allocation, rather than merely
missing history or CloudKit state.

## Remaining sync question

These tests do not yet prove that a raw change, followed only by automatic
CloudKit synchronization and no native app save, is exported to iCloud. The
writer must use a global `ZSYNCOBJECT` primary-key allocator and native GID
format for new Payees. Whether it also needs to enqueue a supported sync
reconciliation step remains an explicit pending experiment.
