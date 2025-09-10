#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import json

from moneywiz_api.moneywiz_api import MoneywizApi


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


def main() -> int:
    ap = argparse.ArgumentParser(description="List MoneyWiz accounts")
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    ap.add_argument("--user", type=int, help="User ID to filter accounts; if omitted, list all users")
    ap.add_argument("--format", choices=["table", "json"], default="table")
    args = ap.parse_args()

    api = MoneywizApi(args.db)
    users = api.accessor.get_users()

    def emit_for_user(uid: int):
        accounts = api.account_manager.get_accounts_for_user(uid)
        return [
            {"user": uid, "id": a.id, "name": a.name, "currency": a.currency}
            for a in accounts
        ]

    rows: list[dict] = []
    if args.user is not None:
        rows = emit_for_user(args.user)
    else:
        for uid in sorted(users.keys()):
            rows.extend(emit_for_user(uid))

    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        print("user\tid\tname\tcurrency")
        for r in rows:
            print(f"{r['user']}\t{r['id']}\t{r['name']}\t{r['currency']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
