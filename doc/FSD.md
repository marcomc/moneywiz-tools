## Functional Specification Document (FSD)

### Overview
The CLI (`moneywiz.sh`) exposes read and write capabilities on a MoneyWiz SQLite DB via the API.

### Functional Areas

1) Read functions
- users: list users.
- accounts: list accounts; filter by user.
- categories: list categories for a user; optional full name chain.
- payees/tags: list; filter by user.
- transactions: list for an account; optional category/tag enrichment; limit/time window.
- holdings: list by investment account.
- record: view single record by `Z_PK` or `ZGID`.
- stats/summary: output snapshots and counts.
- schema/inspect: full schema dump (via scripts/introspect_db.py).

2) Write (Phase 1) — scaffolding and previews
- SQL preview (dry-run default, `--apply` to execute):
  - insert/update/delete SyncObjects.
  - assign-categories (splits) and assign-tags.
  - link-refund.

3) Write (Phase 2+) — typed helpers
- create-transaction: deposit/withdraw/refund/transfer/reconcile/inv-buy/inv-sell/inv-exchange.
- update-transaction: patch fields; maintain relationships.
- create/update account; create/update payee/category/tag; linkages.

### CLI Contract
- Global `--db PATH` before subcommand; default to Setapp path if omitted.
- Subcommands: users, accounts, categories, payees, tags, transactions, holdings, record, stats, summary, sql-preview.
- Safety: dry-run for write flows; `--apply` required to modify DB.

### Data Contracts (inputs/outputs)
- Read outputs: human-readable tables or `--format json` for machine usage.
- Write inputs: flags for simple fields; JSON payloads for complex structures (splits, tags).
- SQL preview: prints ordered SQL statements with parameter lists.

### Errors & Edge Cases
- Missing fields (older DBs): tolerate on reads (derive/skip strict checks).
- FX rounding: use tolerances; skip brittle equality checks.
- Referential integrity: block writes or require `--apply` only when validations pass.

