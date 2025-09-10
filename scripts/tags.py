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
    ap = argparse.ArgumentParser(description="List MoneyWiz tags")
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    ap.add_argument("--user", type=int, help="User ID to filter tags; omit to list all users")
    ap.add_argument("--format", choices=["table", "json"], default="table")
    args = ap.parse_args()

    api = MoneywizApi(args.db)
    records = api.tag_manager.records().values()

    rows = [
        {"user": t.user, "id": t.id, "name": t.name}
        for t in records
        if args.user is None or t.user == args.user
    ]

    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        print("user\tid\tname")
        for r in rows:
            print(f"{r['user']}\t{r['id']}\t{r['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
