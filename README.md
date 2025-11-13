# Moneywiz Tools

CLI tools to explore a local MoneyWiz SQLite database (read‑only), powered by the local `moneywiz-api` source.

## Quick Index

- [Requirements](#requirements)
- [Preparation](#preparation)
- [Quick Start](#quick-start)
- [Optional Config File](#optional-config-file)
- [Adding a Test Database](#adding-a-test-database)
- [Output Format](#output-format)
- [Commands](#commands)
  - [shell](#shell)
  - [users](#users)
  - [accounts](#accounts)
  - [categories](#categories)
  - [payees](#payees)
  - [tags](#tags)
  - [transactions](#transactions)
  - [holdings](#holdings)
  - [record](#record)
  - [stats](#stats)
  - [summary](#summary)
  - [Writes](#writes)
  - [reassign-payees-by-id](#reassign-payees-by-id)
  - [create-test-db](#create-test-db)
  - [sanitize-test-db](#sanitize-test-db)
  - [schema](#schema)
- [Example (all accounts)](#example-all-accounts)
- [Credits & License](#credits--license)

## Requirements

- uv (installs Python deps into `.venv`): [https://docs.astral.sh/uv/getting-started/](https://docs.astral.sh/uv/getting-started/)

## Preparation

`moneywiz.sh` imports the API directly from a sibling `moneywiz-api/` checkout via
`PYTHONPATH`. Run the helper once to bootstrap everything:

```bash
bash moneywiz.sh --setup
```

The setup step clones MarcoMC's fork (needed for write helpers and tolerance fixes) into
`moneywiz-api/` and scaffolds `~/.moneywizrc` with a best-guess MoneyWiz database path.
If the database is not found on your machine the config entry is commented so you can
uncomment it later.

Prefer manual steps? Ensure the directory layout exists before running any other
command:

```bash
git clone https://github.com/marcomc/moneywiz-tools.git
cd moneywiz-tools

# If moneywiz-api/ is missing, clone MarcoMC's fork (required for write helpers)
git clone https://github.com/marcomc/moneywiz-api.git moneywiz-api

# optional: add the upstream remote to stay in sync with ileodo/moneywiz-api
cd moneywiz-api && git remote add upstream https://github.com/ileodo/moneywiz-api.git
cd ..
```

This repo depends on MarcoMC's fork because it contains write helpers and tolerance fixes
that have not landed upstream yet. Keeping `moneywiz-api` up to date is as simple as
pulling the latest commits in that subdirectory (e.g. `cd moneywiz-api && git pull`).
Once the sources exist, `moneywiz.sh` will create `.venv`, install runtime deps, and set
`PYTHONPATH` automatically.

## Quick Start

```bash
./moneywiz.sh users

# Print the usage/help message or run explicitly via bash
bash moneywiz.sh --help

# Seed the bundled test DB from an external MoneyWiz copy (kept outside the repo)
bash moneywiz.sh --db ~/tmp/moneywiz_dev.sqlite --create-test-db

# Scrub/anonymize the bundled test DB after seeding it (always operates on tests/test_db.sqlite and ignores --db option)
bash moneywiz.sh --sanitize-test-db
```

- First run creates `.venv` (Python 3.11) and installs deps.
- Default DB: `tests/test_db.sqlite` (included for development/testing)
- Use your own DB: `./moneywiz.sh --db /path/to/your/ipadMoneyWiz.sqlite <command> [options]`

## Running Tests

Two helper commands cover the API and CLI suites together. From the repo root run:

```bash
bash scripts/run_tests.sh
```

That script bootstraps the `.venv` (via `uv`), installs pytest, sets `PYTHONPATH=moneywiz-api/src`, then runs both `pytest -q moneywiz-api/tests` and `pytest -q tests`. If you prefer to run just the CLI portion, repeat the same environment setup and run:

```bash
PYTHONPATH=moneywiz-api/src .venv/bin/python -m pytest -q tests/cli
```

The `doc/TDD.md` file contains the same guidance along with the overall testing strategy.

## Optional Config File

Create a `.moneywizrc` file to avoid retyping your DB path. The script looks for this file in the
following order (highest priority first):

1. `./moneywiz.sh --db …` (command-line flag always wins)
2. `${HOME}/.moneywizrc`
3. `./.moneywizrc` (next to `moneywiz.sh`)
4. Built-in default: `tests/test_db.sqlite`

Supported keys use `key=value` lines (comments start with `#`). Currently only `db_path` is read. Use `.moneywizrc.example` as a starting template:

```bash
# ~/.moneywizrc
db_path=/Users/me/Library/Containers/com.moneywiz.personalfinance-setapp/Data/Documents/.AppData/ipadMoneyWiz.sqlite
```

## Adding a Test Database

The repo already ships with `tests/test_db.sqlite`, but you can drop in your own MoneyWiz export for more realistic testing:

1. Locate your MoneyWiz database (e.g. `~/Library/Containers/com.moneywiz.personalfinance-setapp/Data/Documents/.AppData/ipadMoneyWiz.sqlite`).
2. Copy it somewhere safe outside of version control (for example `~/tmp/moneywiz_dev.sqlite`) so your real data stays private:

   ```bash
   cp ~/Library/.../ipadMoneyWiz.sqlite ~/tmp/moneywiz_dev.sqlite
   ```

3. Point the CLI/tests at the file via `--db ~/tmp/moneywiz_dev.sqlite` or by setting `db_path=~/tmp/moneywiz_dev.sqlite` in `.moneywizrc`.
4. Run `./moneywiz.sh --db ~/tmp/moneywiz_dev.sqlite --create-test-db` to copy it into `tests/test_db.sqlite`, then `./moneywiz.sh --sanitize-test-db` to scrub names, emails, descriptions, and account/card numbers.
5. (Optional) Keep the sample DB around by duplicating it first: `cp tests/test_db.sqlite tests/test_db.backup.sqlite`.

The CLI validates the path before running any command, so you will get a clear error if the copy goes missing.

## Output Format

- The following subcommands support `--format table|json` (default: `table`):
  - `users`, `accounts`, `categories`, `payees`, `tags`, `transactions`, `holdings`
- Example: `./moneywiz.sh users --format json`

## Commands

### shell

Interactive, read‑only Python shell with prebound helpers.

- Options:
  - `--db PATH` (can be placed before or after `shell`)
  - `--demo-dump`
  - `--log-level [DEBUG|INFO|WARNING|ERROR|CRITICAL]`
- Example:
  
  ```bash
  # Use default DB with demo and debug logs
  ./moneywiz.sh shell --demo-dump --log-level DEBUG

  # Use a specific DB path and enable demo
  ./moneywiz.sh --db \
    "/Users/mmassari/Library/Containers/com.moneywiz.personalfinance-setapp/Data/Documents/.AppData/ipadMoneyWiz.sqlite" \
    shell --demo-dump
  # >>> helper.users_table()
  # >>> helper.accounts_table(2)[["id","name","currency"]]
  ```

- More examples (inside the shell):

  ```python
  # List users
  helper.users_table()

  # Pick a user and explore categories and accounts
  user_id = 2
  helper.categories_table(user_id)[["id", "name", "type"]].head(10)
  helper.accounts_table(user_id)[["id", "name", "currency"]]

  # Pick an account and view recent transactions
  account_id = int(helper.accounts_table(user_id).iloc[0]["id"])  # first account
  helper.transactions_table(account_id)[["id", "datetime", "amount", "description"]].head(10)

  # Inspect specific records by primary ID or global ID (ZGID)
  helper.view_id(4717)
  helper.view_gid("ZGID-EXAMPLE-1234")

  # Investment holdings for an investment account
  invest_acct = account_id  # replace with your investment account id
  helper.investment_holdings_table(invest_acct)

  # Convert any manager's loaded records into a DataFrame
  helper.pd_table(account_manager).head(5)

  # Write simple stats snapshots under data/stats
  helper.write_stats_data_files("data/stats")
  ```

### users

List users in the database.

- Options: `--format [table|json]`
- Example:
  
  ```bash
  ./moneywiz.sh users
  # id   login_name
  # 1    None
  # 2    massaric@gmail.com
  ```

### accounts

List accounts; optionally filter by user.

- Options: `--user <id>`, `--format [table|json]`
- Example:
  
  ```bash
  ./moneywiz.sh accounts --user 2 | sed -n '1,6p'
  # user  id    name                      currency
  # 2     5311  Monzo Flex *3992          GBP
  # 2      965  Prestamo Deposito Casa    EUR
  # ...
  ```

### categories

List categories for a user.

- Options: `--user <id>` (required), `--full-name`, `--format [table|json]`
- Example:
  
  ```bash
  ./moneywiz.sh categories --user 2 | sed -n '1,6p'
  # id    name     type
  # 1490  Salary   Income
  # 8819  Tax      Expenses
  ```

### payees

List payees; optionally filter by user.

- Options: `--user <id>`, `--format [table|json]`, `--sort-by-name`
- Example:
  
  ```bash
  ./moneywiz.sh payees --user 2 --sort-by-name | sed -n '1,5p'
  # user  id    name
  # 2     128   *Setapp
  # 2     176   eBay Commerce UK Ltd
  ```

### tags

List tags; optionally filter by user.

- Options: `--user <id>`, `--format [table|json]`
- Example:
  
  ```bash
  ./moneywiz.sh tags --user 2 | sed -n '1,5p'
  # user  id    name
  # 2     2001  groceries
  # 2     2002  commute
  ```

### transactions

List transactions. If `--account` is omitted, lists across all accounts (excludes budget transfers) in decreasing date order.

- Options: `--account <id>` (optional), `--limit <N>` (use `0` for no limit), `--until YYYY-MM-DD`, `--with-categories`, `--with-tags`, `--all-fields`, `--fields f1,f2,...`, `--list-fields`, `--format [table|json]`
- Example (table):
  
  ```bash
  ./moneywiz.sh transactions --account 5309 --limit 5
  # id     datetime              amount   description
  # 13517  2025-09-09 07:05:54   -2.46    1p Saving Challenge
  # 13559  2025-09-09 00:01:00  1250.52   Marco Massari CaldMonzo-HNMPW
  ```
  
- Example (json details):
  
  ```bash
  ./moneywiz.sh transactions --account 5309 --limit 2 --with-categories --with-tags --format json | jq
  # [
  #   {"id": 13517, "categories": [{"category_id": 7127, "amount": "-2.46"}], "tags": [...]},
  #   {"id": 13559, "categories": [{"category_id": 1490, "amount": "1250.52"}], "tags": []}
  # ]
  ```

- Example (all fields as JSON):
  
  ```bash
  ./moneywiz.sh transactions --account 5309 --limit 1 --all-fields --format json | jq
  # [
  #   {
  #     "__type__": "DepositTransaction",
  #     "id": 13559,
  #     "gid": "...",
  #     "account": 5309,
  #     "amount": "1250.52",
  #     "description": "...",
  #     "datetime": "2025-09-09 00:01:00",
  #     "... other model fields ...",
  #     "__raw": { ... filtered raw ... },
  #     "__raw_all": { ... complete raw row ... }
  #   }
  # ]
  ```

- Example (select fields in table mode):
  
  ```bash
  ./moneywiz.sh transactions --account 5309 --limit 3 --fields id,account,account_name,payee,payee_name,amount,original_currency,original_amount
  # id  account  account_name  payee  payee_name  amount  original_currency  original_amount
  # ...
  ```

- Example (all fields in table mode):
  
  ```bash
  ./moneywiz.sh transactions --account 5309 --limit 1 --all-fields
  # Prints a wide table including all available top-level fields (the same
  # set you see with --list-fields). Raw DB fields are not merged; for raw
  # values use --format json to inspect __raw / __raw_all.
  ```

- Discover fields available for --fields (based on current selection):
  
  ```bash
  ./moneywiz.sh transactions --account 5309 --limit 100 --list-fields
  # account
  # account_name
  # amount
  # datetime
  # description
  # id
  # original_amount
  # original_currency
  # original_exchange_rate
  # payee
  # ...
  ```

### holdings

List investment holdings for an account.

- Options: `--account <id>` (required), `--format [table|json]`
- Example:
  
  ```bash
  ./moneywiz.sh holdings --account 7824 | sed -n '1,5p'
  # account  symbol  number_of_shares  description
  # 7824     AAPL    12.345            Apple Inc.
  # 7824     TSLA     3.210            Tesla, Inc.
  ```

### record

View a record by primary key ID or global ID (ZGID).

- Options: `--id <pk>` OR `--gid <ZGID>`
- Example:
  
  ```bash
  ./moneywiz.sh record --id 4717
  # Account
  # { "id": 4717, "name": "EasyAccess", "currency": "GBP", ... }
  ```

### stats

Write simple text snapshots for core components to an output directory.

- Options: `--out <dir>` (default: `data/stats`)
- Example:
  
  ```bash
  ./moneywiz.sh stats --out data/stats
  # Wrote stats files under data/stats
  ```

### summary

Print counts per manager.

- Example:
  
  ```bash
  ./moneywiz.sh summary
  # Users: 2 -> {1: None, 2: "massaric@gmail.com"}
  # Accounts: 49
  # Categories: 90
  # Transactions: 13559
  # Investment holdings: 42
  # Tags: 35
  ```

### Writes

Preview (and optionally apply) write operations with a safe dry-run by default. Add `--apply` to execute on the DB (recommended only on a copy). Use global `--db` before the command to point to a specific DB.

- Commands (top-level):
  - `insert --type <Z_PRIMARYKEY.Z_NAME> --fields '<JSON cols>'`
  - `update --id <Z_PK> --fields '<JSON cols>'`
  - `delete --id <Z_PK>`
  - `safe-delete --id <Z_PK>`
  - `rename --id <Z_PK> --name "New Name" [--name-field ZNAME|ZDESC2|...]`
  - `assign-categories --tx <ID> --splits '<JSON [[cat,amount], ...]>'`
  - `assign-tags --tx <ID> --tags '<JSON [tag_id, ...]>'`
  - `link-refund --refund <ID> --withdraw <ID>`

- What gets updated/inserted:
  - `insert` and `update` operate on the core `ZSYNCOBJECT` table that backs all MoneyWiz entities (transactions, accounts, payees, tags, categories, etc.).
    - `insert`: sets `Z_ENT` by looking up the typename in `Z_PRIMARYKEY.Z_NAME`, and fills sensible defaults like `Z_OPT`, `ZGID`, `ZOBJECTCREATIONDATE`.
    - `update`: updates a specific row by `Z_PK` regardless of logical type; you pass only the columns you want to change.
  - Relationship helpers write to their specific tables:
    - `assign-categories` → `ZCATEGORYASSIGMENT` rows for a transaction’s splits
    - `assign-tags` → `Z_36TAGS` join rows linking a transaction to tags
    - `link-refund` → `ZWITHDRAWREFUNDTRANSACTIONLINK` linking refund ↔ original withdraw
  - See per-type create recipes in `doc/FIELD-MAPPINGS.md` for minimal field sets and examples.

- Safety and convenience:
  - `safe-delete`: scans all schema tables/INTEGER columns for rows referencing the target `Z_PK`. If any references are found, it aborts and prints a summary like `ZCATEGORYASSIGMENT.ZCATEGORY: 3 (sample ids: ...)` so you can clean up first.
  - `rename`: updates a name-bearing column for the entity. If `--name-field` is not provided, it tries common columns in order: `ZNAME`, `ZDESC2`, `ZTITLE2`.

Examples:

```bash
# Dry-run insert of a DepositTransaction
./moneywiz.sh --db tests/test_db.sqlite insert \
  --type DepositTransaction \
  --fields '{"ZACCOUNT2":5309, "ZAMOUNT1":12.34, "ZDATE1":700000000, "ZDESC2":"Test deposit"}'

# Apply tag assignment (use with caution; test on a DB copy)
./moneywiz.sh --db tests/test_db.sqlite assign-tags --apply \
  --tx 13517 --tags '[3001,3002]'

# Rename an entity (detect name column automatically)
./moneywiz.sh --db tests/test_db.sqlite rename --id 965 --name "Savings Vault"

# Prevent deletion if referenced; show references instead of deleting
./moneywiz.sh --db tests/test_db.sqlite safe-delete --id 965
```

### reassign-payees-by-id

Reassign transactions currently referencing a given payee id so that each transaction instead references a payee whose name equals the transaction's description (per user). Creates missing payees as needed.

- Usage: `./moneywiz.sh reassign-payees-by-id --from-payee-id <ID> [--apply]`
Example:

```bash
# Preview reassignments away from payee 2874
./moneywiz.sh reassign-payees-by-id --from-payee-id 2874

# Apply the changes
./moneywiz.sh reassign-payees-by-id --from-payee-id 2874 --apply
```

### create-test-db

Copy the currently selected MoneyWiz database into `tests/test_db.sqlite`. The source DB is resolved in the same order as other commands (`--db` override → `.moneywizrc` → default path).

- Example:
  ```bash
  ./moneywiz.sh --db ~/tmp/moneywiz_dev.sqlite create-test-db
  # Created test DB at tests/test_db.sqlite (copied from ~/tmp/moneywiz_dev.sqlite)
  ```

### sanitize-test-db

Scrub/anonymize `tests/test_db.sqlite` after seeding it. The command prints a verbose summary of every column updated so you can confirm no personal data remains.

- Example:
  ```bash
  ./moneywiz.sh sanitize-test-db
  # ... per-column summary ...
  ```

### schema

Generate a full schema dump (Markdown) and a machine-readable JSON dump for any DB.

- Usage: `./moneywiz.sh schema [--out-md PATH] [--out-json PATH]`
- Defaults:
  - `--out-md doc/DB-SCHEMA.md`
  - `--out-json doc/schema.json`

Examples:

```bash
# Generate using default test DB to default locations
./moneywiz.sh schema

# Generate for a custom DB to a temp directory
./moneywiz.sh --db /path/to/your/ipadMoneyWiz.sqlite schema \
  --out-md /tmp/DB-SCHEMA.md --out-json /tmp/schema.json
```

## Example (all accounts)

```bash
./moneywiz.sh transactions --limit 10
# Shows latest 10 transactions across all accounts
```

## Credits & License

- Moneywiz Tools is maintained by Marco Massari Calderone and released under the MIT License (see `LICENSE`).
- The project builds directly on—and is heavily inspired by—the excellent [`moneywiz-api`](https://github.com/ileodo/moneywiz-api) library by Tianwei Dong (ileodo). We vendor MarcoMC’s fork of that project to pick up write helpers and bug fixes while contributing improvements back upstream.
- MoneyWiz is a product of [SilverWiz Ltd.](https://silverwiz.com/). This project is an independent, open-source tool and is not affiliated with SilverWiz Ltd.
