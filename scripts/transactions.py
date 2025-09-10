#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
from datetime import datetime
import json

from moneywiz_api.moneywiz_api import MoneywizApi


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


def parse_date(val: str | None) -> datetime | None:
    if not val:
        return None
    return datetime.fromisoformat(val)


def main() -> int:
    ap = argparse.ArgumentParser(description="List MoneyWiz transactions for an account")
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    ap.add_argument("--account", type=int, required=True, help="Account ID to list transactions for")
    ap.add_argument("--limit", type=int, default=50, help="Max rows to output (default 50)")
    ap.add_argument("--until", type=str, help="Include transactions up to this ISO date (YYYY-MM-DD)")
    ap.add_argument("--with-categories", action="store_true", help="Include category assignments")
    ap.add_argument("--with-tags", action="store_true", help="Include tags for each transaction")
    ap.add_argument("--format", choices=["table", "json"], default="table")
    args = ap.parse_args()

    api = MoneywizApi(args.db)
    until_dt = parse_date(args.until) or datetime.now()
    txs = api.transaction_manager.get_all_for_account(args.account, until=until_dt)
    txs = list(reversed(txs))[: args.limit]

    rows: list[dict] = []
    for t in txs:
        item: dict = {
            "id": t.id,
            "datetime": t.datetime.isoformat(sep=" ", timespec="seconds"),
            "amount": str(t.amount),
            "description": t.description,
        }
        if args.with_categories:
            cats = api.transaction_manager.category_for_transaction(t.id) or []
            item["categories"] = [{"category_id": cid, "amount": str(amt)} for cid, amt in cats]
        if args.with_tags:
            tags = api.transaction_manager.tags_for_transaction(t.id) or []
            item["tags"] = tags
        rows.append(item)

    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        base_headers = ["id", "datetime", "amount", "description"]
        print("\t".join(base_headers))
        for r in rows:
            print("\t".join(str(r[h]) for h in base_headers))
        if args.with_categories:
            print("\n# categories: use --format json to see per-transaction details")
        if args.with_tags:
            print("# tags: use --format json to see per-transaction details")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
