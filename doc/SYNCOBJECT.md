# Sync Object Model

## Purpose

`ZSYNCOBJECT` is the shared Core Data storage layer behind multiple logical
MoneyWiz entities. It carries object identity, entity type, and optimistic
version data that are part of the synchronization contract.

## Live profile

| Field | Meaning | Rule |
| --- | --- | --- |
| `Z_PK` | SQLite object identity | Preserve existing identity. |
| `ZGID` | Sync/global identity | Do not fabricate for live writes. |
| `Z_ENT` | Core Data entity discriminator | Interpret only with the active model. |
| `Z_OPT` | Optimistic-lock version | Let Core Data manage it for live writes. |

Subtype-specific fields are not globally stable. For the observed live
payee profile, the name is `ZNAME5` and ownership is `ZUSER7`. Other entity
versions and test fixtures can use different column names or entity values.

## Relationship contract

A live payee affects more than a display name:

- Transaction rows can point at the payee through `ZPAYEE2`.
- `ZSTRINGHISTORYITEM.ZPAYEE` records payee-related string history.
- The associated Core Data object lifecycle must publish persistent history
  understood by the app and CloudKit.

The current Core Data writer handles reassignment, destination creation, and
exact duplicate consolidation. The merge enumerates model relationships that
target `Payee`, then deletes the source through the same Core Data lifecycle.
Similar-name consolidation remains excluded until its approval workflow is
implemented.

## Identity allocation

Do not use `Z_PRIMARYKEY.Z_MAX` as a live object-ID allocator. The observed
store has a global `ZSYNCOBJECT.Z_PK` identity space, and Core Data owns
identity creation for the compatible writer path.

## Scope of raw SQL mappings

Field mappings can still support inspection, diagnostics, and test-copy
experiments. They are not a substitute for the live Core Data contract. See
[Field Mappings](FIELD-MAPPINGS.md) for broader mapping evidence and
[Live Payee Structure](LIVE-PAYEE-STRUCTURE.md) for the versioned live
profile.
