# Core Concepts and Conventions

This document captures important conventions in the MoneyWiz database that help when extending the API and CLI.

## Timestamps (Apple epoch)

- The DB stores many timestamps as floats relative to 2001‑01‑01 00:00:00 UTC (Apple epoch).
- Conversion is provided by the installed `moneywiz_api` module; see the
  [`get_datetime` and `get_date` helpers](https://github.com/marcomc/moneywiz-api/blob/6ea3cdec8b1543356e00f6b529450b5aa1b39264/src/moneywiz_api/utils.py#L6-L15).
  - `get_datetime(raw)`: returns Python `datetime` from DB float.
  - `get_date(dt)`: converts Python `datetime` to DB float.

## Amounts and precision

- SQLite stores numeric fields as floats; the API converts monetary values to `Decimal` for precision (see model classes and `RawDataHandler`).
- When comparing computed amounts, allow small absolute tolerances due to FX rounding.

## Signs and transaction semantics

- Expenses (outflow): negative amounts; Incomes (inflow): positive.
- Transfers: two linked transactions (withdraw + deposit) with opposite signs; ensure amounts/FX/fees are consistent across sides.
- Refunds: positive transactions that map back to the original negative withdraw; see `ZWITHDRAWREFUNDTRANSACTIONLINK`.

## Relationships

- Category splits: `ZCATEGORYASSIGMENT` with `(ZTRANSACTION, ZCATEGORY, ZAMOUNT)`; totals should sum to the transaction amount (respect sign).
- Tags: `Z_36TAGS` with `(Z_36TRANSACTIONS, Z_35TAGS)`.
- Refund link: `ZWITHDRAWREFUNDTRANSACTIONLINK` with `(ZREFUNDTRANSACTION, ZWITHDRAWTRANSACTION)`.

## Entity typing and lookup

- Resolve `Z_ENT`↔`Z_NAME` via `Z_PRIMARYKEY`.
- The API’s `DatabaseAccessor` caches both maps to avoid repeated lookups.

## Optimistic versioning

- `Z_OPT` is a Core Data version field. Native app updates increment it.
- Do not assume an initial value for a new live object from the generic SQL
  helper. The observed live payees have values greater than one; the native
  creation sequence still needs a pre/post capture.
- Updating `Z_OPT` alone is insufficient for a live iCloud store. See
  `LIVE-WRITE-COMPATIBILITY.md` for the associated history and CloudKit state.

## GIDs (Global IDs)

- `ZGID` is a UUID-like identifier for a row; set a new UUID for inserted objects to keep global uniqueness.

## Column naming patterns

- Several logical fields have numeric suffixes (e.g., `ZAMOUNT1`, `ZDATE1`, `ZNAME5`). These reflect positions in the Core Data model and are reused across entity types.
- Use the model classes in the API to see how raw columns map to domain fields.

## Error tolerance and data quirks

- Legacy/synced DBs may contain missing FX fields (e.g., `ZORIGINALAMOUNT`), zeros, or blank currencies. The API is tolerant (derives or skips strict assertions) to facilitate read‑only access.
- When adding write flows, be stricter and validate FX coherence, totals, and cross‑links.

## Recommended write practices

- Do not use raw SQL as a product write path.
- Use a named `moneywiz` operation only after
  `moneywiz compatibility --capability NAME` reports `verified`.
- Treat a SQLite transaction as atomicity only, not as a replacement for a
  Core Data persistent-history transaction.
- Version every live-write rule by MoneyWiz app build, Core Data model
  fingerprint, and the profile-capability register.

## Live payees and consolidation

- The current live MoneyWiz 2026 mapping stores `Payee` as
  `ZSYNCOBJECT.Z_ENT=29`, with its name in `ZNAME5` and user in `ZUSER7`.
  These are model-version-specific subtype columns; do not reuse the test DB
  mapping or query the generic `ZNAME` column for a live payee.
- A transaction's payee relationship is stored in `ZPAYEE2`, while
  `ZSTRINGHISTORYITEM.ZPAYEE` retains additional payee references. A payee
  merge must account for both, through Core Data, before deleting a duplicate.
- Payee matching is user-scoped and uses NFKC normalization, collapsed
  whitespace, and case folding. Fuzzy similarity is a review aid only; it is
  not evidence that two merchants are interchangeable.
- The detailed compatibility profile and merge constraints are in
  [`LIVE-PAYEE-STRUCTURE.md`](LIVE-PAYEE-STRUCTURE.md).
