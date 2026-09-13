from __future__ import annotations

import argparse
import json
from pathlib import Path

from moneywiz_api.moneywiz_api import MoneywizApi
from read_support import (
    json_value,
    report_completeness,
    run_read_command,
    validate_selected_account,
)


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="List MoneyWiz investment holdings for an account"
    )
    ap.add_argument(
        "--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB"
    )
    ap.add_argument(
        "--account", type=int, required=True, help="Account ID to list holdings for"
    )
    ap.add_argument("--format", choices=["table", "json"], default="table")
    ap.add_argument(
        "--diagnostics",
        action="store_true",
        help="Wrap JSON rows with completeness metadata",
    )
    args = ap.parse_args()
    if args.diagnostics and args.format != "json":
        ap.error("--diagnostics requires --format json")

    api = MoneywizApi(args.db, managers=("accounts", "investment_holdings"))
    try:
        validate_selected_account(api, args.account)
        holdings = api.investment_holding_manager.get_holdings_for_account(args.account)
        rows = [
            {
                "account": h.account,
                "symbol": h.symbol,
                "number_of_shares": json_value(h.number_of_shares),
                "description": h.description,
            }
            for h in holdings
        ]
        report, status = report_completeness(api)
    finally:
        api.close()
    if args.format == "json":
        print(
            json.dumps(
                {"rows": rows, "completeness": report} if args.diagnostics else rows,
                indent=2,
            )
        )
    else:
        print("account\tsymbol\tnumber_of_shares\tdescription")
        for r in rows:
            print(
                f"{r['account']}\t{r['symbol']}\t{r['number_of_shares']}\t{r['description']}"
            )
    return status


if __name__ == "__main__":
    raise SystemExit(run_read_command(main))
