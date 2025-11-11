#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Literal

Rule = Literal["CLEAR", "EMAIL"] | str

SANITIZE_RULES: dict[str, Rule] = {
    "ZNAME": "NAME",
    "ZNAME2": "CAT",
    "ZNAME5": "PAYEE",
    "ZNAME6": "TAG",
    "ZDESC": "DESC",
    "ZDESC2": "DESC",
    "ZDESC3": "DESC",
    "ZNOTES1": "CLEAR",
    "ZACCOUNTNUMBER": "ACC",
    "ZCARDNUMBER": "CARD",
    "ZEMAIL": "EMAIL",
    "ZUSEREMAIL": "EMAIL",
    "ZGID": "ZGID",
}

USER_RULES: dict[str, Rule] = {
    "ZSYNCLOGIN": "user",
    "ZEMAIL": "EMAIL",
}


def column_exists(con: sqlite3.Connection, table: str, column: str) -> bool:
    cur = con.execute(f"PRAGMA table_info({table})")
    return any(row[1].upper() == column.upper() for row in cur.fetchall())


def apply_rule(con: sqlite3.Connection, table: str, column: str, rule: Rule) -> None:
    if not column_exists(con, table, column):
        return
    rule_upper = rule.upper() if isinstance(rule, str) else rule
    if rule_upper == "CLEAR":
        con.execute(f"UPDATE {table} SET {column} = NULL WHERE {column} IS NOT NULL")
    elif rule_upper == "EMAIL":
        con.execute(
            f"UPDATE {table} SET {column} = 'user_' || Z_PK || '@example.com' WHERE {column} IS NOT NULL"
        )
    else:
        prefix = rule
        con.execute(
            f"UPDATE {table} SET {column} = ? || Z_PK WHERE {column} IS NOT NULL",
            (f"{prefix}_",),
        )


def sanitize_syncobject(con: sqlite3.Connection) -> None:
    for column, rule in SANITIZE_RULES.items():
        apply_rule(con, "ZSYNCOBJECT", column, rule)


def sanitize_users(con: sqlite3.Connection) -> None:
    if not column_exists(con, "ZUSER", "Z_PK"):
        return
    for column, rule in USER_RULES.items():
        apply_rule(con, "ZUSER", column, rule)


def anonymize_payee_names(con: sqlite3.Connection) -> None:
    # Some builds keep payee names in dedicated tables; ensure they are blanked too
    if column_exists(con, "ZPAYEE", "ZNAME"):
        con.execute("UPDATE ZPAYEE SET ZNAME = 'PAYEE_' || Z_PK")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sanitize/anonymize tests/test_db.sqlite")
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"Database not found: {args.db}")

    con = sqlite3.connect(str(args.db))
    try:
        sanitize_syncobject(con)
        sanitize_users(con)
        anonymize_payee_names(con)
        con.commit()
    finally:
        con.close()

    print(f"Sanitized and anonymized test database at {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
