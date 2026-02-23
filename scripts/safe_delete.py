#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from moneywiz_api.writes import WriteSession


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


def main() -> int:
    ap = argparse.ArgumentParser(description="Safely delete a row if no references exist; otherwise report references")
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    ap.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    ap.add_argument("--id", type=int, required=True, help="Z_PK of the row to delete")
    args = ap.parse_args()

    session = WriteSession(args.db, dry_run=(not args.apply))
    if args.apply:
        with session.transaction():
            refs = session.safe_delete(args.id)
    else:
        refs = session.safe_delete(args.id)
    if refs:
        print("-- ABORT: References found; not deleting --")
        for r in refs:
            samples = ", ".join(map(str, r.sample_ids)) if r.sample_ids else ""
            suffix = f" (sample ids: {samples})" if samples else ""
            print(f"- {r.table}.{r.column}: {r.count}{suffix}")
        session.close()
        return 2

    print("-- " + ("APPLY" if args.apply else "DRY-RUN") + " --")
    for i, step in enumerate(session.planned, start=1):
        print(f"[{i}] SQL: {step.sql}")
        if step.params is not None:
            print(f"    params: {step.params}")
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
