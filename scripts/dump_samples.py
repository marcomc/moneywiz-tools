#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

from moneywiz_api.moneywiz_api import MoneywizApi
from moneywiz_api.cli.helpers import ShellHelper


def main() -> int:
    # DB path: arg0 or default Setapp path
    db_path = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"
    )

    # Defaults
    user_id = int(os.getenv("MW_USER", "2"))
    account_id = int(os.getenv("MW_ACCOUNT", "5309"))  # Monzo Personal per prior dump
    tx_limit = int(os.getenv("MW_TX_LIMIT", "20"))

    api = MoneywizApi(db_path)
    helper = ShellHelper(api)

    pd.options.display.max_rows = None
    pd.options.display.max_colwidth = None

    print("=== Users ===")
    print(helper.users_table().to_string(index=False))
    print()

    print(f"=== Categories for user {user_id} ===")
    cats = helper.categories_table(user_id)[["id", "name", "type"]]
    print(cats.to_string(index=False))
    print()

    print(f"=== Accounts for user {user_id} ===")
    accts = helper.accounts_table(user_id)[["id", "name", "currency"]]
    print(accts.to_string(index=False))
    print()

    print(f"=== Last {tx_limit} transactions for account {account_id} ===")
    tx = helper.transactions_table(account_id)[["id", "datetime", "amount", "description"]].head(tx_limit)
    print(tx.to_string(index=False))
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
