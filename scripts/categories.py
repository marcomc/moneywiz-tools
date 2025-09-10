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
    ap = argparse.ArgumentParser(description="List MoneyWiz categories")
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    ap.add_argument("--user", type=int, required=True, help="User ID to list categories for")
    ap.add_argument("--full-name", action="store_true", help="Include parent→child name chain")
    ap.add_argument("--format", choices=["table", "json"], default="table")
    args = ap.parse_args()

    api = MoneywizApi(args.db)
    cats = api.category_manager.get_categories_for_user(args.user)

    rows: list[dict] = []
    for c in cats:
        item = {"id": c.id, "name": c.name, "type": c.type}
        if args.full_name:
            item["name_chain"] = "/".join(api.category_manager.get_name_chain(c.id))
        rows.append(item)

    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        headers = ["id", "name", "type"] + (["name_chain"] if args.full_name else [])
        print("\t".join(headers))
        for r in rows:
            print("\t".join(str(r.get(h, "")) for h in headers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
