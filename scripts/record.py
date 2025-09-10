#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import json

from moneywiz_api.moneywiz_api import MoneywizApi


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


def main() -> int:
    ap = argparse.ArgumentParser(description="View a MoneyWiz record by ID or GID")
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", type=int, help="Record primary key ID")
    group.add_argument("--gid", type=str, help="Record global ID (ZGID)")
    args = ap.parse_args()

    api = MoneywizApi(args.db)
    if args.id is not None:
        rec = api.accessor.get_record(args.id)
    else:
        rec = api.accessor.get_record_by_gid(args.gid)

    typename = api.accessor.typename_for(rec.ent())
    print(typename)
    print(json.dumps(rec.filtered(), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
