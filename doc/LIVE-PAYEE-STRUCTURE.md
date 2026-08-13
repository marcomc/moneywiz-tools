# Live Payee Structure (MoneyWiz 2026)

## Scope and compatibility boundary

This live-store profile uses `MoneyWizDataModel 48`. It was captured with
MoneyWiz 2026.32.1 build 431 on 2026-08-08 and revalidated with build 433 on
2026-08-13.

It supplements the generated [`DB-SCHEMA.md`](DB-SCHEMA.md) test fixture. Do
not transfer entity numbers or physical column mappings from that fixture to a
live iCloud store: the observed test fixture maps `Payee` to `Z_ENT=28` and
`Transaction` to `Z_ENT=36`, while this live profile maps them to `29` and
`37` respectively.

The store's `Z_METADATA.Z_VERSION` is Core Data metadata, not the MoneyWiz
model version. Record the app version, build, selected `.mom` version, and the
`NSStoreModelVersionChecksumKey` from `Z_METADATA.Z_PLIST` for every new
compatibility profile. The current exact checksum is recorded in
[`LIVE-WRITE-COMPATIBILITY.md`](LIVE-WRITE-COMPATIBILITY.md).

## Entity storage

MoneyWiz stores several domain entities in the inherited `ZSYNCOBJECT` table.
`Z_ENT` is the runtime discriminator and must be resolved through
`Z_PRIMARYKEY` for the store being operated on.

| Domain entity | Observed live `Z_ENT` | Physical storage |
| --- | ---: | --- |
| `Payee` | 29 | `ZSYNCOBJECT` |
| `Transaction` | 37 | `ZSYNCOBJECT` |
| Transaction subclasses | 38-48 | `ZSYNCOBJECT` |
| `StringHistoryItem` | Separate entity | `ZSTRINGHISTORYITEM` |

The global `ZSYNCOBJECT.Z_PK` keyspace is shared across inherited entity types.
`Z_PRIMARYKEY.Z_MAX` is not a valid allocator for new objects in this store
generation. New object creation must go through the Core Data writer rather
than handwritten primary-key or identity allocation.

## Observed payee and transaction mapping

For the current live profile, the logical `Payee` properties use subtype
columns, not the generic `ZNAME` and `ZUSER` columns.

| Logical value | Observed storage | Notes |
| --- | --- | --- |
| Payee identity | `ZSYNCOBJECT.Z_PK`, `ZGID` | `Z_PK` is local; `ZGID` is the sync identity. |
| Payee type | `ZSYNCOBJECT.Z_ENT = 29` | Resolve again after model migration. |
| Payee name | `ZSYNCOBJECT.ZNAME5` | Do not query `ZNAME` for this entity. |
| Payee user | `ZSYNCOBJECT.ZUSER7` | Matching and consolidation are scoped to this user. |
| Optimistic version | `ZSYNCOBJECT.Z_OPT` | Managed by Core Data. |
| Transaction payee | `ZSYNCOBJECT.ZPAYEE2` | Applies to transaction entity 37 and its subclasses. |
| Payee text history | `ZSTRINGHISTORYITEM.ZPAYEE`, `ZSTRING` | Audit before merge. |

Useful live-only inspection query:

```sql
SELECT Z_PK, ZGID, ZNAME5, ZUSER7, Z_OPT
FROM ZSYNCOBJECT
WHERE Z_ENT = 29
ORDER BY ZUSER7, ZNAME5 COLLATE NOCASE, Z_PK;
```

## Name normalization and ambiguity

The canonical match key used by `reassign-payees-by-id` is:

1. Unicode NFKC normalization.
2. Whitespace collapsing.
3. Unicode case folding.

This is required because the live store can contain non-breaking spaces
(`U+00A0`) and all-uppercase variants of otherwise identical names. Matching
must occur within the same payee user. For a new normalized key, the selected
transaction with the lowest persistent ID supplies the display name; every
operation for that user-scoped key uses the same value.

Exact duplicate keys are safe to classify as duplicate candidates, but not to
select silently: the chosen surviving ID determines the name retained by the
UI. A consolidation policy should prefer an approved normal-spaced,
non-all-uppercase spelling when one exists. The tool must reject a group with
no explicit canonical decision rather than choosing by primary key.

Fuzzy name similarity is discovery-only. It produces false positives for
merchant branch suffixes, order references, month-specific interest entries,
and directional transfer descriptions. Never merge fuzzy candidates without an
explicit user-to-canonical-payee mapping.

## Consolidation requirements

A payee merge is a graph mutation, not only a transaction update. Before
deleting a duplicate payee, the writer must account for at least:

| Relationship | Required action |
| --- | --- |
| `Transaction.payee` | Reassign every affected transaction to the canonical payee. |
| `StringHistoryItem.payee` | Preserve or deliberately migrate historical string associations. |
| Other model relationships | Inspect through the current Core Data model before deletion. |

The plan must be regenerated from a fresh read-only snapshot immediately
before `--apply`; automatic iCloud synchronization can invalidate a stale
inventory between planning and writing.

Do not delete a live payee with raw SQL. Use the same Core Data context that
performs relationship changes, save one persistent-history transaction, and
let the model's delete rules manage inverse relationships. Quit MoneyWiz
before applying, then reopen it and wait for iCloud Sync to report `Up to
Date`.

## Writer evidence

The production writer is the `MoneyWizTools` executable inside the single
`MoneyWiz Tools.app` bundle. It writes with `transactionAuthor =
MWLocalAuthor`, its own bundle identifier, and Core Data persistent history.
On the observed build, MoneyWiz consumed that history and produced its normal
CloudKit export state. The writer must not manufacture `ANSCK*` metadata or
encoded CloudKit record assets directly.

See [`CORE-DATA-WRITER.md`](CORE-DATA-WRITER.md) for the host contract and
[`LIVE-WRITE-COMPATIBILITY.md`](LIVE-WRITE-COMPATIBILITY.md) for the evidence
and historical experiments.
