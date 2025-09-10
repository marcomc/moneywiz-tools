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
    ap = argparse.ArgumentParser(description="List MoneyWiz investment holdings for an account")
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    ap.add_argument("--account", type=int, required=True, help="Account ID to list holdings for")
    ap.add_argument("--format", choices=["table", "json"], default="table")
    args = ap.parse_args()

    api = MoneywizApi(args.db)
    holdings = api.investment_holding_manager.get_holdings_for_account(args.account)

    rows = [
        {
            "account": h.account,
            "symbol": h.symbol,
            "number_of_shares": str(h.number_of_shares),
            "description": h.description,
        }
        for h in holdings
    ]

    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        print("account\tsymbol\tnumber_of_shares\tdescription")
        for r in rows:
            print(f"{r['account']}\t{r['symbol']}\t{r['number_of_shares']}\t{r['description']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
