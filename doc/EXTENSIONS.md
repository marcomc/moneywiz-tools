# Extensions Roadmap — moneywiz-api + moneywiz.sh

This document outlines practical read/write extensions to the current read-only library so that core MoneyWiz features can be replicated from the CLI.

Guiding principles

- Keep database integrity: respect existing relationships and Core Data conventions.
- Prefer small, composable operations with clear preconditions and validations.
- Transaction-safe writes: wrap multi-table updates (e.g., transfers, category/tag links) in a single DB transaction.

## Entities and Operations

### Users

- Read: list users (implemented).
- Write: N/A (created by the app/cloud sync). Avoid creating users manually.

### Accounts

- Read: list, filter by user (implemented).
- Write (add/update/archive):
  - Create account rows in `ZSYNCOBJECT` with appropriate `Z_ENT` for type.
  - Fields: `ZNAME`, `ZCURRENCYNAME`, `ZDISPLAYORDER`, `ZGROUPID`, `ZUSER`, `ZOPENINGBALANCE`.
  - Consider “archived” flag (toggle), include/exclude from net worth.
  - Helpers: resolve `Z_ENT` from `Z_PRIMARYKEY`.

### Payees

- Read: list (implemented).
- Write: create/update payee rows in `ZSYNCOBJECT` for the Payee entity type; fields `ZNAME5`, `ZUSER7`.

### Categories

- Read: list, name chains (implemented).
- Write: create/update `Category` rows in `ZSYNCOBJECT`, set parent via `ZPARENTCATEGORY`, `ZTYPE2`.

### Tags

- Read: list (implemented).
- Write: create/update `Tag` rows in `ZSYNCOBJECT`; link to transactions via `Z_36TAGS` rows.

### Transactions

- Read: all types (implemented) + splits/tags/refunds maps (implemented).
- Write (core):
  - Deposit/Withdraw/Refund: create `ZSYNCOBJECT` rows with FX fields as applicable.
  - Transfers: create two linked rows (withdraw+deposit) and maintain both sides (`recipient/sender` account + transaction ids) with correct signs and FX/fee.
  - Reconcile: create entries with new balance or share count.
  - Investment buy/sell/exchange: create entries for each subtype with shares, price per share, fees.
- Write (relationships):
  - Category splits: insert into `ZCATEGORYASSIGMENT` per transaction, amounts summing to transaction value (by sign).
  - Tags: insert rows into `Z_36TAGS` per tag.
  - Refund links: create `ZWITHDRAWREFUNDTRANSACTIONLINK` row mapping refund to original withdraw.

### Holdings

- Read: by account (implemented).
- Write: update holdings meta (e.g., `ZDESC`, `ZHOLDINGTYPE`), update price table if desired (requires additional tables not currently modeled).

## Low-level Accessor Changes

Add a write-capable `DatabaseAccessor` API with transaction helpers:

- `begin()/commit()/rollback()` or context manager.
- `insert_syncobject(typename: str, fields: dict) -> int` — resolve `Z_ENT`, set mandatory columns (`Z_OPT`, `ZGID`), and insert. Return `Z_PK`.
- `update_syncobject(pk: int, fields: dict)` — patch fields.
- `delete_syncobject(pk: int)` — cautious; ensure no dependent rows.
- Helper mappers: `ent_for/typename_for` (exists), `now_to_coredata_timestamp()`, currency helpers.

Relationship helpers:

- `assign_categories(tx_id: int, splits: list[tuple[cat_id, Decimal]])` — maintain sums/signs.
- `assign_tags(tx_id: int, tag_ids: list[int])` — upsert bridge rows.
- `link_refund(refund_tx_id: int, original_withdraw_id: int)`.

## CLI Design (moneywiz.sh)

New subcommands (sketch):

- `create-account --user ID --type <BankCheque|Cash|CreditCard|...> --name NAME --currency CUR [--opening-balance AMOUNT]`
- `update-account --id ID [--name N] [--currency C] [--archived BOOL] ...`
- `create-transaction --type <deposit|withdraw|refund|transfer|reconcile|inv-buy|inv-sell|inv-exchange> [type-specific flags]`
- `update-transaction --id ID [--amount A] [--description S] [--notes S] [--datetime ISO] ...`
- `assign-categories --tx ID --split cat:amt --split cat:amt ...`
- `assign-tags --tx ID --tags TAG_ID,TAG_ID,...`
- `link-refund --refund ID --original-withdraw ID`

Safeguards:

- Dry-run (`--dry-run`) to emit SQL changes without applying.
- `--json` inputs for complex payloads (splits, tags).
- Balancing checks for category splits and transfer consistency.

## Data Constraints & Pitfalls

- Core Data fields often duplicate semantics across entity types (e.g., `ZAMOUNT1`, `ZDATE1`, `ZDESC2`). Keep a mapping per type.
- Signs: expenses are negative, income positive; transfers are paired entries with opposite signs.
- FX fields: `ZORIGINALAMOUNT`, `ZORIGINALCURRENCY`, `ZORIGINALEXCHANGERATE` should be coherent; tolerate rounding.
- Global IDs (`ZGID`) should be unique; generate UUIDs when inserting.
- `Z_OPT` is a Core Data version field; set to `1` on insert, increment on updates.
- Add/maintain indexes for large tables if write-heavy workflows are introduced (Careful: app updates may recreate DB).

## Research To‑Dos (external)

Due to restricted network access here, capture these for future refinement:

- Confirm full set of `ZSYNCOBJECT` `Z_ENT` → `Z_NAME` mappings for all MoneyWiz versions.
- Validate write semantics expected by the app (e.g., which flags/arrays must be kept in sync).
- Investigate MoneyWiz sync side effects (cloud or iCloud) and how local changes are detected.

## Implementation Plan (phased)

1. Write layer scaffolding

- Add `write` methods on `DatabaseAccessor` with transaction helpers; unit tests against a temporary DB copy.

1. CRUD for core types

- Accounts: create/update; Transactions: deposit/withdraw; Payees/Categories/Tags: create.

1. Relationships

- Category splits, tag links, refund links, transfer pairs (consistency checks).

1. Advanced

- Investment transactions (buy/sell/exchange), reconcile flows, holdings metadata.

1. CLI integration

- Add subcommands, dry-run support, and JSON input; document in README.md and `doc/`.
