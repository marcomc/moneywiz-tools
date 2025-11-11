#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from moneywiz_api.writes import WriteSession


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


def main() -> int:
    ap = argparse.ArgumentParser(description="Rename an entity row in ZSYNCOBJECT")
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    ap.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--name-field", help="Explicit column to update (e.g., ZNAME, ZDESC2)")
    args = ap.parse_args()

    session = WriteSession(args.db, dry_run=(not args.apply))
    session.rename_entity(args.id, args.name, args.name_field)

    print("-- " + ("APPLY" if args.apply else "DRY-RUN") + " --")
    for i, step in enumerate(session.planned, start=1):
        print(f"[{i}] SQL: {step.sql}")
        if step.params is not None:
            print(f"    params: {step.params}")
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

