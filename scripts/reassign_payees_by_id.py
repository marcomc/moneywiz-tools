#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any

from moneywiz_api.writes import WriteSession


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


TRANSACTION_TYPENAMES: tuple[str, ...] = (
    "DepositTransaction",
    "InvestmentExchangeTransaction",
    "InvestmentBuyTransaction",
    "InvestmentSellTransaction",
    "ReconcileTransaction",
    "RefundTransaction",
    "TransferBudgetTransaction",
    "TransferDepositTransaction",
    "TransferWithdrawTransaction",
    "WithdrawTransaction",
)


def _dict_connection(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path), uri=True)

    def dict_factory(cursor, row):
        record = {}
        for idx, col in enumerate(cursor.description):
            record[col[0]] = row[idx]
        return record

    con.row_factory = dict_factory
    return con


def _ent_for(con: sqlite3.Connection, typename: str) -> int:
    row = con.execute(
        "SELECT Z_ENT FROM Z_PRIMARYKEY WHERE Z_NAME = ? LIMIT 1", (typename,)
    ).fetchone()
    if not row:
        raise ValueError(f"Unknown typename '{typename}' in Z_PRIMARYKEY")
    return int(row["Z_ENT"])


def _ents_for(con: sqlite3.Connection, typenames: tuple[str, ...]) -> list[int]:
    return [_ent_for(con, t) for t in typenames]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Reassign transactions away from a given payee id: for each matching transaction, "
            "create/find a payee whose name is exactly the transaction's description (per user), "
            "and update the transaction to reference that payee."
        )
    )
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    ap.add_argument("--from-payee-id", type=int, required=True, help="Payee id to replace in transactions")
    ap.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run preview)")
    ap.add_argument("--quiet", action="store_true", help="Suppress per-transaction logs; show only the summary")
    ap.add_argument("--show-plan", action="store_true", help="Print planned SQL (useful for debugging)")
    args = ap.parse_args()

    # Avoid MoneywizApi() here: it eagerly parses *all* transactions, and some
    # real-world MoneyWiz DBs contain NULLs in fields that the upstream API
    # currently asserts as non-null (e.g. TransferDepositTransaction.ZORIGINALAMOUNT).
    con = _dict_connection(args.db)
    session = WriteSession(args.db, dry_run=(not args.apply))

    print("-- " + ("APPLY" if args.apply else "DRY-RUN") + " --")

    # Build lookup (name,user) -> payee_id for exact matches
    payees_by_name_user: dict[tuple[str, int], int] = {}
    payee_ent = _ent_for(con, "Payee")
    for row in con.execute(
        "SELECT Z_PK, ZNAME5, ZUSER7 FROM ZSYNCOBJECT WHERE Z_ENT = ?",
        (payee_ent,),
    ).fetchall():
        name = row.get("ZNAME5")
        user = row.get("ZUSER7")
        if name is None or user is None:
            continue
        payees_by_name_user[(str(name), int(user))] = int(row["Z_PK"])

    created = 0
    updated = 0
    processed = 0

    # Find candidate transactions by payee id, scoped to known transaction entities.
    tx_ents = _ents_for(con, TRANSACTION_TYPENAMES)
    tx_ent_placeholders = ",".join("?" * len(tx_ents))
    tx_rows = con.execute(
        (
            "SELECT Z_PK, ZACCOUNT2, ZDESC2 "
            "FROM ZSYNCOBJECT "
            f"WHERE Z_ENT IN ({tx_ent_placeholders}) AND ZPAYEE2 = ?"
        ),
        (*tx_ents, args.from_payee_id),
    ).fetchall()

    # Resolve account -> user for the accounts involved (transaction rows reference ZACCOUNT2).
    account_ids = sorted({int(r["ZACCOUNT2"]) for r in tx_rows if r.get("ZACCOUNT2") is not None})
    account_user_by_id: dict[int, int] = {}
    if account_ids:
        account_placeholders = ",".join("?" * len(account_ids))
        for row in con.execute(
            f"SELECT Z_PK, ZUSER FROM ZSYNCOBJECT WHERE Z_PK IN ({account_placeholders})",
            account_ids,
        ).fetchall():
            if row.get("ZUSER") is None:
                continue
            account_user_by_id[int(row["Z_PK"])] = int(row["ZUSER"])

    for row in tx_rows:
        tx_id = int(row["Z_PK"])
        processed += 1

        desc = row.get("ZDESC2")
        if not desc:
            if not args.quiet:
                print(f"Skip tx {tx_id}: empty description")
            continue

        account_id = row.get("ZACCOUNT2")
        if account_id is None:
            if not args.quiet:
                print(f"Skip tx {tx_id}: account not found")
            continue

        user_id = account_user_by_id.get(int(account_id))
        if user_id is None:
            if not args.quiet:
                print(f"Skip tx {tx_id}: account user not found")
            continue

        key = (desc, user_id)
        target_payee_id = payees_by_name_user.get(key)

        if target_payee_id is None:
            # Create payee with exact name for this user (if applying)
            new_id = session.insert_syncobject("Payee", {"ZNAME5": desc, "ZUSER7": user_id})
            if new_id is None:
                if not args.quiet:
                    print(
                        f"[PLAN] Create payee name='{desc}' user={user_id} and update tx {tx_id} (id will be assigned on apply)"
                    )
                created += 1
                # Cannot update TX in dry-run without knowing the id; continue to next
                continue
            target_payee_id = new_id
            payees_by_name_user[key] = target_payee_id
            created += 1
            if not args.quiet:
                print(f"Created payee '{desc}' (id={target_payee_id}) for user {user_id}")

        # Update transaction's payee reference
        session.update_syncobject(tx_id, {"ZPAYEE2": target_payee_id})
        updated += 1
        # Always confirm in apply mode; in dry-run only if not quiet
        if args.apply or not args.quiet:
            print(f"Updated tx {tx_id} -> payee {target_payee_id} ('{desc}')")

    # Print planned/apply SQL steps
    if args.show_plan:
        print("\nPlanned SQL steps:")
        for i, step in enumerate(session.planned, start=1):
            print(f"[{i}] SQL: {step.sql}")
            if step.params is not None:
                print(f"    params: {step.params}")

    print(f"\nSummary: processed={processed}, created={created}, updated={updated}")
    con.close()
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
