#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Literal

Rule = Literal["CLEAR", "EMAIL"] | str

SANITIZE_RULES: dict[str, Rule] = {
    "ZNAME": "ACCOUNT",
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


def apply_rule(
    con: sqlite3.Connection, table: str, column: str, rule: Rule, summary: dict[str, int]
) -> None:
    if not column_exists(con, table, column):
        print(f"- {table}.{column}: column missing, skipping")
        return
    cur = con.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NOT NULL")
    count = cur.fetchone()[0]
    if count == 0:
        print(f"- {table}.{column}: no data to sanitize")
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
    key = f"{table}.{column}"
    summary[key] = summary.get(key, 0) + count
    print(f"- {key}: sanitized {count} entr{'y' if count == 1 else 'ies'}")


def sanitize_syncobject(con: sqlite3.Connection, summary: dict[str, int]) -> None:
    for column, rule in SANITIZE_RULES.items():
        apply_rule(con, "ZSYNCOBJECT", column, rule, summary)


def sanitize_users(con: sqlite3.Connection, summary: dict[str, int]) -> None:
    if not column_exists(con, "ZUSER", "Z_PK"):
        print("- ZUSER: table missing, skipping user sanitization")
        return
    for column, rule in USER_RULES.items():
        apply_rule(con, "ZUSER", column, rule, summary)


def anonymize_payee_names(con: sqlite3.Connection, summary: dict[str, int]) -> None:
    # Some builds keep payee names in dedicated tables; ensure they are blanked too
    if column_exists(con, "ZPAYEE", "ZNAME"):
        cur = con.execute("SELECT COUNT(*) FROM ZPAYEE WHERE ZNAME IS NOT NULL")
        count = cur.fetchone()[0]
        con.execute("UPDATE ZPAYEE SET ZNAME = 'PAYEE_' || Z_PK WHERE ZNAME IS NOT NULL")
        summary["ZPAYEE.ZNAME"] = summary.get("ZPAYEE.ZNAME", 0) + count
        print(f"- ZPAYEE.ZNAME: sanitized {count} entries")
    else:
        print("- ZPAYEE.ZNAME: column missing, skipping")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sanitize/anonymize tests/test_db.sqlite")
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"Database not found: {args.db}")

    con = sqlite3.connect(str(args.db))
    summary: dict[str, int] = {}
    try:
        sanitize_syncobject(con, summary)
        sanitize_users(con, summary)
        anonymize_payee_names(con, summary)
        con.commit()
    finally:
        con.close()

    total = sum(summary.values())
    print("\nSanitized columns summary:")
    if summary:
        for key in sorted(summary):
            count = summary[key]
            print(f"  * {key}: {count} entr{'y' if count == 1 else 'ies'} updated")
    else:
        print("  * No columns required updates; database already sanitized")
    print(f"\nSanitized and anonymized test database at {args.db} (total entries touched: {total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
