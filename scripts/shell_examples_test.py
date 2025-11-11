#!/usr/bin/env python3
"""
Non-interactive smoke test for README shell examples.

Runs a subset of helper calls against the bundled test DB to ensure
examples in the README remain valid.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure local source tree is importable
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "moneywiz-api" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from moneywiz_api.moneywiz_api import MoneywizApi  # type: ignore
from moneywiz_api.cli.helpers import ShellHelper  # type: ignore


def main() -> int:
    db_path = REPO_ROOT / "tests" / "test_db.sqlite"
    api = MoneywizApi(str(db_path))
    helper = ShellHelper(api)

    # 1) Users table
    users_df = helper.users_table()
    print(f"OK users_table: shape={users_df.shape}")
    assert not users_df.empty, "users_table should not be empty"

    # Choose a user (prefer an id > 1 if present)
    user_ids = users_df["id"].tolist()
    user_id = next((uid for uid in user_ids if uid != 1), user_ids[0])
    print(f"Using user_id={user_id}")

    # 2) Categories and Accounts tables
    cats_df = helper.categories_table(user_id)[["id", "name", "type"]]
    print(f"OK categories_table: shape={cats_df.shape}")
    accts_df = helper.accounts_table(user_id)[["id", "name", "currency"]]
    print(f"OK accounts_table: shape={accts_df.shape}")
    assert not accts_df.empty, "accounts_table should not be empty"

    # 3) Transactions table for first account
    first_account_id = int(accts_df.iloc[0]["id"])
    tx_df = helper.transactions_table(first_account_id)[
        ["id", "datetime", "amount", "description"]
    ].head(10)
    print(
        f"OK transactions_table(account_id={first_account_id}): rows={len(tx_df.index)}"
    )

    # 4) Record views by id/gid (id for chosen account)
    print("OK view_id: printing type and filtered JSON for first account")
    helper.view_id(first_account_id)

    # 5) Investment holdings table (may be empty or not applicable)
    try:
        holdings_df = helper.investment_holdings_table(first_account_id)
        print(
            f"OK investment_holdings_table(account_id={first_account_id}): shape={holdings_df.shape}"
        )
    except Exception as exc:  # noqa: BLE001 - log and continue
        print(
            f"SKIP investment_holdings_table(account_id={first_account_id}): {exc.__class__.__name__}: {exc}"
        )

    # 6) Convert records to DataFrame via pd_table
    acct_df = helper.pd_table(api.account_manager).head(5)
    print(f"OK pd_table(account_manager): rows={len(acct_df.index)}")

    # 7) Write stats files
    out_dir = REPO_ROOT / "data" / "stats_test"
    helper.write_stats_data_files(out_dir)
    wrote = list(out_dir.glob("*.data"))
    print(f"OK write_stats_data_files: wrote={len(wrote)} files to {out_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
