#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from moneywiz_api.writes import WriteSession


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


def load_fields(json_str: str | None) -> dict[str, Any]:
    if not json_str:
        return {}
    return json.loads(json_str)


def main() -> int:
    ap = argparse.ArgumentParser(description="Insert a ZSYNCOBJECT row for a typename")
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    ap.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    ap.add_argument("--type", required=True, help="Type name as in Z_PRIMARYKEY.Z_NAME (e.g., 'DepositTransaction')")
    ap.add_argument("--fields", help="JSON object with column:value pairs")
    args = ap.parse_args()

    session = WriteSession(args.db, dry_run=(not args.apply))
    session.insert_syncobject(args.type, load_fields(args.fields))

    print("-- " + ("APPLY" if args.apply else "DRY-RUN") + " --")
    for i, step in enumerate(session.planned, start=1):
        print(f"[{i}] SQL: {step.sql}")
        if step.params is not None:
            print(f"    params: {step.params}")
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

