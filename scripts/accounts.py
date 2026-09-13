from __future__ import annotations

import argparse
import json
from pathlib import Path

from moneywiz_api.moneywiz_api import MoneywizApi
from read_support import report_completeness, run_read_command


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


def main() -> int:
    ap = argparse.ArgumentParser(description="List MoneyWiz accounts")
    ap.add_argument(
        "--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB"
    )
    ap.add_argument(
        "--user",
        type=int,
        help="User ID to filter accounts; if omitted, list all users",
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

    with MoneywizApi(args.db, managers=("accounts",)) as api:
        if args.user is None:
            accounts = api.account_manager.records().values()
        else:
            accounts = api.account_manager.get_accounts_for_user(args.user)
        rows = [
            {
                "user": account.user,
                "id": account.id,
                "name": account.name,
                "currency": account.currency,
            }
            for account in accounts
        ]
        report, status = report_completeness(api)
    if args.format == "json":
        print(
            json.dumps(
                {"rows": rows, "completeness": report} if args.diagnostics else rows,
                indent=2,
            )
        )
    else:
        print("user\tid\tname\tcurrency")
        for r in rows:
            print(f"{r['user']}\t{r['id']}\t{r['name']}\t{r['currency']}")
    return status


if __name__ == "__main__":
    raise SystemExit(run_read_command(main))
