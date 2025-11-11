#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from moneywiz_api.moneywiz_api import MoneywizApi
from moneywiz_api.writes import WriteSession


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


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

    api = MoneywizApi(args.db)
    session = WriteSession(args.db, dry_run=(not args.apply))

    print("-- " + ("APPLY" if args.apply else "DRY-RUN") + " --")

    # Build lookup (name,user) -> payee_id for exact matches
    payees_by_name_user: dict[tuple[str, int], int] = {}
    for p in api.payee_manager.records().values():
        payees_by_name_user[(p.name, p.user)] = p.id

    created = 0
    updated = 0
    processed = 0

    # Iterate all transactions and find those with the source payee id
    for tx in api.transaction_manager.records().values():
        current_payee = getattr(tx, "payee", None)
        if current_payee != args.from_payee_id:
            continue
        processed += 1

        desc = getattr(tx, "description", None)
        if not desc:
            # Skip transactions without a description
            if not args.quiet:
                print(f"Skip tx {tx.id}: empty description")
            continue

        account = api.account_manager.get(getattr(tx, "account", None))
        if account is None:
            if not args.quiet:
                print(f"Skip tx {tx.id}: account not found")
            continue

        user_id = account.user
        key = (desc, user_id)
        target_payee_id = payees_by_name_user.get(key)

        if target_payee_id is None:
            # Create payee with exact name for this user (if applying)
            new_id = session.insert_syncobject("Payee", {"ZNAME5": desc, "ZUSER7": user_id})
            if new_id is None:
                if not args.quiet:
                    print(
                        f"[PLAN] Create payee name='{desc}' user={user_id} and update tx {tx.id} (id will be assigned on apply)"
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
        session.update_syncobject(tx.id, {"ZPAYEE2": target_payee_id})
        updated += 1
        # Always confirm in apply mode; in dry-run only if not quiet
        if args.apply or not args.quiet:
            print(f"Updated tx {tx.id} -> payee {target_payee_id} ('{desc}')")

    # Print planned/apply SQL steps
    if args.show_plan:
        print("\nPlanned SQL steps:")
        for i, step in enumerate(session.planned, start=1):
            print(f"[{i}] SQL: {step.sql}")
            if step.params is not None:
                print(f"    params: {step.params}")

    print(f"\nSummary: processed={processed}, created={created}, updated={updated}")
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
