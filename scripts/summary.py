#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

from moneywiz_api.moneywiz_api import MoneywizApi


def default_db() -> Path:
    return Path(
        os.path.expanduser(
            "~/Library/Containers/com.moneywiz.personalfinance-setapp/Data/Documents/.AppData/ipadMoneyWiz.sqlite"
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Summary of MoneyWiz data by manager")
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    args = ap.parse_args()

    api = MoneywizApi(args.db)
    users = api.accessor.get_users()
    print(f"Users: {len(users)} -> {users}")
    print(f"Accounts: {len(api.account_manager.records())}")
    print(f"Payees: {len(api.payee_manager.records())}")
    print(f"Categories: {len(api.category_manager.records())}")
    print(f"Transactions: {len(api.transaction_manager.records())}")
    print(f"Investment holdings: {len(api.investment_holding_manager.records())}")
    print(f"Tags: {len(api.tag_manager.records())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

