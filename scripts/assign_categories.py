#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from moneywiz_api.writes import WriteSession


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


def main() -> int:
    ap = argparse.ArgumentParser(description="Assign category splits to a transaction")
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    ap.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    ap.add_argument("--tx", type=int, required=True)
    ap.add_argument("--splits", required=True, help="JSON array of [category_id, amount]")
    args = ap.parse_args()

    session = WriteSession(args.db, dry_run=(not args.apply))
    splits = json.loads(args.splits)
    if args.apply:
        with session.transaction():
            session.assign_categories(args.tx, [(int(c), a) for c, a in splits])
    else:
        session.assign_categories(args.tx, [(int(c), a) for c, a in splits])

    print("-- " + ("APPLY" if args.apply else "DRY-RUN") + " --")
    for i, step in enumerate(session.planned, start=1):
        print(f"[{i}] SQL: {step.sql}")
        if step.params is not None:
            print(f"    params: {step.params}")
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
