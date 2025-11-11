# MoneyWiz CLI — Functions

This document summarizes the capabilities exposed by the MoneyWiz CLI included in this repository. The CLI is implemented in `moneywiz-api/src/moneywiz_api/cli/cli.py` and installed as the `moneywiz-cli` command (see `moneywiz-api/pyproject.toml`).

## Overview

- Read-only interactive shell over a MoneyWiz SQLite database.
- Quick demo dump of sample data (users, categories, accounts).
- Tab-completion and rich DataFrame views via `pandas`.
- Convenience helper functions for inspecting records and exporting simple stats files.

## Invocation

- Command: `moneywiz-cli [DB_FILE_PATH] [--demo-dump] [--log-level LEVEL]`
- `DB_FILE_PATH`: Path to MoneyWiz SQLite file. Defaults to macOS path `~/Library/Containers/com.moneywiz.personalfinance/Data/Documents/.AppData/ipadMoneyWiz.sqlite`.
- `--demo-dump, -d`: Prints a short demo of users, categories, and accounts to the console before entering the shell.
- `--log-level`: One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (default: `INFO`).

## Interactive Environment

When the shell starts, the following pre-bound objects are available:

- `moneywiz_api`: Root API object (`MoneywizApi`).
- `accessor`: Low-level DB accessor (`DatabaseAccessor`).
- `account_manager`: Accounts manager.
- `payee_manager`: Payees manager.
- `category_manager`: Categories manager.
- `transaction_manager`: Transactions manager.
- `investment_holding_manager`: Investment holdings manager.
- `tag_manager`: Tags manager.
- `helper`: Shell utilities (`ShellHelper`) for quick inspection and table views.

Tab completion is enabled for these names and their attributes. `pandas` display options are adjusted to show full rows/columns in the session.

## Helper Utilities (`helper`)

- `helper.view_id(record_id)`: Print the entity type and JSON for a record by primary ID.
- `helper.view_gid(record_gid)`: Print the entity type and JSON for a record by global ID (GID).
- `helper.users_table() -> pd.DataFrame`: List users (`id`, `login_name`).
- `helper.categories_table(user_id) -> pd.DataFrame`: List categories for a user.
- `helper.accounts_table(user_id) -> pd.DataFrame`: List accounts for a user, sorted by group/display order.
- `helper.investment_holdings_table(account_id) -> pd.DataFrame`: List holdings for an account.
- `helper.transactions_table(account_id) -> pd.DataFrame`: List transactions for an account (newest first).
- `helper.pd_table(manager) -> pd.DataFrame`: Convert any manager’s loaded records to a DataFrame.
- `helper.write_stats_data_files(path_prefix='data/stats')`: Write simple text snapshots for core managers to files under the given directory.

## Managers — Data Access (Read-only)

Managers load and cache records from the database and offer typed helpers:

- `account_manager`
  - `records()`: All accounts keyed by ID (sorted by display order).
  - `get_accounts_for_user(user_id)`: Accounts for a given user.
- `category_manager`
  - `records()`: All categories.
  - `get_categories_for_user(user_id)`: Categories for a user.
  - `get_name_chain(category_id | category_gid)`: Full parent→child name chain.
- `transaction_manager`
  - `records()`: All transactions.
  - `get_all_for_account(account_id, until=datetime.now())`: Account transactions (excludes budget transfers), up to a given time.
  - `get_all(until=datetime.now())`: All transactions (excludes budget transfers).
  - `category_for_transaction(transaction_id)`: Category assignments with amounts.
  - `tags_for_transaction(transaction_id)`: Tag IDs linked to a transaction.
  - `original_transaction_for_refund_transaction(transaction_id)`: Original withdraw for a refund.
- `investment_holding_manager`
  - `records()`: All investment holdings.
  - `get_holdings_for_account(account_id)`: Holdings for a given account.
- `payee_manager`, `tag_manager`
  - `records()`: All payees or tags.

Low-level accessor (`accessor`) provides:

- `typename_for(ent_id)` / `ent_for(typename)`: Map entity type IDs and names.
- `query_objects(typenames)`: Raw rows for given entity type names.
- `get_record(pk_id)` / `get_record_by_gid(gid)`: Fetch a single raw record.
- `get_users()`: Map of user IDs to login names.
- `get_category_assignment()`, `get_refund_maps()`, `get_tags_map()`: Transaction relationships and mappings.

## Demo Dump (`--demo-dump`)

If enabled, before starting the shell the CLI prints:

- Users table.
- A random user’s sample categories and accounts (subset) as formatted tables.

## Notes

- The CLI and API are read-only; write/update actions are not implemented.
- The session uses the current process’s logging configuration set via `--log-level`.
