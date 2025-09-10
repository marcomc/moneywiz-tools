# Core Concepts and Conventions

This document captures important conventions in the MoneyWiz database that help when extending the API and CLI.

## Timestamps (Apple epoch)
- The DB stores many timestamps as floats relative to 2001‑01‑01 00:00:00 UTC (Apple epoch).
- Conversion in the API: see `moneywiz-api/src/moneywiz_api/utils.py:1`.
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
- `Z_OPT` acts as a version field; set to `1` on insert and increment on update to mirror Core Data behavior if you want to emulate conflicts explicitly.

## GIDs (Global IDs)
- `ZGID` is a UUID-like identifier for a row; set a new UUID for inserted objects to keep global uniqueness.

## Column naming patterns
- Several logical fields have numeric suffixes (e.g., `ZAMOUNT1`, `ZDATE1`, `ZNAME5`). These reflect positions in the Core Data model and are reused across entity types.
- Use the model classes in the API to see how raw columns map to domain fields.

## Error tolerance and data quirks
- Legacy/synced DBs may contain missing FX fields (e.g., `ZORIGINALAMOUNT`), zeros, or blank currencies. The API is tolerant (derives or skips strict assertions) to facilitate read‑only access.
- When adding write flows, be stricter and validate FX coherence, totals, and cross‑links.

## Recommended write practices
- Use transactions when touching multiple tables.
- For complex creates (e.g., transfers): create both sides first, then link by setting the cross‑referenced transaction ids.
- For category splits: validate that sums match the transaction amount.
- For tags: avoid duplicate links; consider upserts or deduping before insert.
- Always dry‑run and review SQL before applying to a real database.
