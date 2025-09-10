#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from moneywiz_api.writes import WriteSession


def load_fields(json_str: str | None) -> dict[str, Any]:
    if not json_str:
        return {}
    return json.loads(json_str)


def main() -> int:
    ap = argparse.ArgumentParser(description="Preview (and optionally apply) SQL writes to MoneyWiz DB")
    ap.add_argument("--db", type=Path, required=True, help="Path to MoneyWiz sqlite DB")
    ap.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run preview)")

    sub = ap.add_subparsers(dest="cmd", required=True)

    ins = sub.add_parser("insert", help="Insert a ZSYNCOBJECT row for a typename")
    ins.add_argument("--type", required=True, help="Type name as in Z_PRIMARYKEY.Z_NAME (e.g., 'DepositTransaction')")
    ins.add_argument("--fields", help="JSON object with column:value pairs")

    upd = sub.add_parser("update", help="Update a ZSYNCOBJECT row by primary key")
    upd.add_argument("--id", type=int, required=True, help="Z_PK of the row")
    upd.add_argument("--fields", required=True, help="JSON object with column:value pairs")

    dele = sub.add_parser("delete", help="Delete a ZSYNCOBJECT row by primary key")
    dele.add_argument("--id", type=int, required=True)

    cats = sub.add_parser("assign-categories", help="Assign category splits to a transaction")
    cats.add_argument("--tx", type=int, required=True)
    cats.add_argument("--splits", required=True, help="JSON array of [category_id, amount]")

    tags = sub.add_parser("assign-tags", help="Assign tags to a transaction")
    tags.add_argument("--tx", type=int, required=True)
    tags.add_argument("--tags", required=True, help="JSON array of tag ids")

    refund = sub.add_parser("link-refund", help="Link a refund transaction to its original withdraw")
    refund.add_argument("--refund", type=int, required=True)
    refund.add_argument("--withdraw", type=int, required=True)

    args = ap.parse_args()

    session = WriteSession(args.db, dry_run=(not args.apply))

    if args.cmd == "insert":
        session.insert_syncobject(args.type, load_fields(args.fields))
    elif args.cmd == "update":
        session.update_syncobject(args.id, load_fields(args.fields))
    elif args.cmd == "delete":
        session.delete_syncobject(args.id)
    elif args.cmd == "assign-categories":
        splits = json.loads(args.splits)
        session.assign_categories(args.tx, [(int(c), a) for c, a in splits])
    elif args.cmd == "assign-tags":
        tag_ids = [int(x) for x in json.loads(args.tags)]
        session.assign_tags(args.tx, tag_ids)
    elif args.cmd == "link-refund":
        session.link_refund(args.refund, args.withdraw)

    # Print the plan
    print("-- " + ("APPLY" if args.apply else "DRY-RUN") + " --")
    for i, step in enumerate(session.planned, start=1):
        print(f"[{i}] SQL: {step.sql}")
        if step.params is not None:
            print(f"    params: {step.params}")

    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

