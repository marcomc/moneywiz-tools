#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import json

from moneywiz_api.moneywiz_api import MoneywizApi


def default_db() -> Path:
    # Default to repo test DB
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


def main() -> int:
    ap = argparse.ArgumentParser(description="List MoneyWiz users")
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    ap.add_argument("--format", choices=["table", "json"], default="table")
    args = ap.parse_args()

    api = MoneywizApi(args.db)
    users = api.accessor.get_users()

    rows = [{"id": uid, "login_name": name} for uid, name in sorted(users.items())]
    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        print("id\tlogin_name")
        for r in rows:
            print(f"{r['id']}\t{r['login_name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
