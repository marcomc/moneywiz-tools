#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
import json
import sys


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"

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


def main() -> int:
    ap = argparse.ArgumentParser(description="List MoneyWiz payees")
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    ap.add_argument("--user", type=int, help="User ID to filter payees; omit to list all users")
    ap.add_argument("--format", choices=["table", "json"], default="table")
    ap.add_argument("--sort-by-name", action="store_true", help="Sort payees by name (A→Z)")
    args = ap.parse_args()

    # Avoid MoneywizApi() here: it eagerly parses *all* transactions, and some
    # real-world MoneyWiz DBs contain NULLs in fields that the upstream API
    # currently asserts as non-null (e.g. TransferDepositTransaction.ZORIGINALAMOUNT).
    con = _dict_connection(args.db)
    payee_ent = _ent_for(con, "Payee")

    rows = [
        {"user": int(r["ZUSER7"]), "id": int(r["Z_PK"]), "name": r["ZNAME5"]}
        for r in con.execute(
            "SELECT Z_PK, ZUSER7, ZNAME5 FROM ZSYNCOBJECT WHERE Z_ENT = ?",
            (payee_ent,),
        ).fetchall()
        if r.get("ZUSER7") is not None
        and r.get("ZNAME5") is not None
        and (args.user is None or int(r["ZUSER7"]) == args.user)
    ]
    # Stable sort: by id by default; by lowercased name if requested
    if args.sort_by_name:
        rows.sort(key=lambda r: (str(r["name"]).lower(), r["id"]))
    else:
        rows.sort(key=lambda r: r["id"])  # deterministic output

    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        print("user\tid\tname")
        for r in rows:
            print(f"{r['user']}\t{r['id']}\t{r['name']}")
    con.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        # Allow piping to tools like `head` without noisy tracebacks.
        try:
            sys.stdout.close()
        finally:
            raise SystemExit(0)
