from __future__ import annotations

import argparse
import json
from pathlib import Path

from moneywiz_api.moneywiz_api import MoneywizApi
from read_support import json_value, report_completeness, run_read_command


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


def _account_was_observed(account_report: dict, account_id: int) -> bool:
    source_ids = {
        record_id
        for record_id in account_report.get("source_ids", [])
        if type(record_id) is int
    }
    skipped_ids = {
        skipped.get("record_id")
        for skipped in account_report.get("skipped", [])
        if type(skipped.get("record_id")) is int
    }
    return account_id in source_ids | skipped_ids


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
        account_records = api.account_manager.records()
        if args.account not in account_records:
            account_report = api.completeness().as_dict()["managers"]["accounts"]
            if not _account_was_observed(account_report, args.account):
                raise ValueError("requested account does not exist")
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
