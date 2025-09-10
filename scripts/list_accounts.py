#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

from moneywiz_api.moneywiz_api import MoneywizApi


def main() -> int:
    # DB path: arg0 or default Setapp path
    db_path = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"
    )

    api = MoneywizApi(db_path)
    users = api.accessor.get_users()

    printed_any = False
    for uid, login in sorted(users.items()):
        accounts = api.account_manager.get_accounts_for_user(uid)
        print(f"User {uid} ({login}) — {len(accounts)} accounts")
        print("id\tname\tcurrency")
        for a in accounts:
            print(f"{a.id}\t{a.name}\t{a.currency}")
        print()
        printed_any = True

    if not printed_any:
        print("No users/accounts found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
