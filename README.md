# MoneyWiz Tools

CLI tools to explore a local MoneyWiz SQLite database (read‑only), powered by the local `moneywiz-api` source.

## Requirements

- uv (installs Python deps into `.venv`): https://docs.astral.sh/uv/getting-started/

## Quick Start

```bash
./moneywiz.sh users
```

- First run creates `.venv` (Python 3.11) and installs deps.
- Default DB: `tests/test_db.sqlite` (included for development/testing)
- Use your own DB: `./moneywiz.sh --db /path/to/your/ipadMoneyWiz.sqlite <command> [options]`

## Commands

### shell
Interactive, read‑only Python shell with prebound helpers.

- Options:
  - `--demo-dump`
  - `--log-level [DEBUG|INFO|WARNING|ERROR|CRITICAL]`
- Example:
  ```bash
  ./moneywiz.sh shell --demo-dump --log-level DEBUG
  # >>> helper.users_table()
  # >>> helper.accounts_table(2)[["id","name","currency"]]
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

- Options: `--user <id>`, `--format [table|json]`
- Example:
  ```bash
  ./moneywiz.sh payees --user 2 | sed -n '1,5p'
  # user  id    name
  # 2     1001  Amazon
  # 2     1002  Starbucks
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
List transactions for an account (excludes budget transfers).

- Options: `--account <id>` (required), `--limit <N>`, `--until YYYY-MM-DD`, `--with-categories`, `--with-tags`, `--format [table|json]`
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

### sql-preview
Preview (and optionally apply) SQL changes using a safe dry-run layer. By default, no changes are applied; add `--apply` to execute on the DB (recommended only on a copy).

- Base usage: `./moneywiz.sh sql-preview --db <db.sqlite> <command> [options]`
- Commands:
  - `insert --type <Z_PRIMARYKEY.Z_NAME> --fields '<JSON cols>'`
  - `update --id <Z_PK> --fields '<JSON cols>'`
  - `delete --id <Z_PK>`
  - `assign-categories --tx <ID> --splits '<JSON [[cat,amount], ...]>'`
  - `assign-tags --tx <ID> --tags '<JSON [tag_id, ...]>'`
  - `link-refund --refund <ID> --withdraw <ID>`

Examples:

```bash
# Dry-run insert of a DepositTransaction
./moneywiz.sh sql-preview --db tests/test_db.sqlite insert \
  --type DepositTransaction \
  --fields '{"ZACCOUNT2":5309, "ZAMOUNT1":12.34, "ZDATE1":700000000, "ZDESC2":"Test deposit"}'

# Apply tag assignment (use with caution; test on a DB copy)
./moneywiz.sh sql-preview --db tests/test_db.sqlite --apply assign-tags \
  --tx 13517 --tags '[3001,3002]'
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

## Notes

- Everything is read‑only; your MoneyWiz DB is never modified.
- macOS defaults are baked in; override any time with `--db`.
