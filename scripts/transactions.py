#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
from datetime import datetime
import json

from moneywiz_api.moneywiz_api import MoneywizApi


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


def parse_date(val: str | None) -> datetime | None:
    if not val:
        return None
    return datetime.fromisoformat(val)


def main() -> int:
    ap = argparse.ArgumentParser(description="List MoneyWiz transactions for an account")
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    ap.add_argument(
        "--account",
        type=int,
        required=False,
        help="Account ID to list transactions for. If omitted, lists transactions from all accounts",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max rows to output (0 = no limit; default 0)",
    )
    ap.add_argument("--until", type=str, help="Include transactions up to this ISO date (YYYY-MM-DD)")
    ap.add_argument("--with-categories", action="store_true", help="Include category assignments")
    ap.add_argument("--with-tags", action="store_true", help="Include tags for each transaction")
    ap.add_argument(
        "--all-fields",
        action="store_true",
        help="Include all available fields for each transaction (adds type, model fields, and raw filtered columns). Use with --format json for full fidelity.",
    )
    ap.add_argument(
        "--fields",
        type=str,
        help="Comma-separated list of fields to print in table mode (implies enrichment so model fields are present).",
    )
    ap.add_argument(
        "--list-fields",
        action="store_true",
        help="List available top-level fields for --fields (based on current selection)",
    )
    ap.add_argument("--format", choices=["table", "json"], default="table")
    args = ap.parse_args()

    api = MoneywizApi(args.db)
    until_dt = parse_date(args.until) or datetime.now()
    if args.account is not None:
        txs = api.transaction_manager.get_all_for_account(args.account, until=until_dt)
    else:
        txs = api.transaction_manager.get_all(until=until_dt)
    # Sort newest first and apply optional limit (0 or negative means no limit)
    txs = list(reversed(txs))
    if args.limit and args.limit > 0:
        txs = txs[: args.limit]

    def sanitize(obj):
        try:
            from decimal import Decimal
        except Exception:
            Decimal = None  # type: ignore
        try:
            from datetime import datetime as _dt
        except Exception:
            _dt = None  # type: ignore
        if isinstance(obj, dict):
            return {k: sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [sanitize(x) for x in obj]
        if Decimal is not None and isinstance(obj, Decimal):
            return str(obj)
        if _dt is not None and isinstance(obj, _dt):
            return obj.isoformat(sep=" ", timespec="seconds")
        return obj

    rows: list[dict] = []
    need_enrich = bool(args.all_fields or args.fields or args.list_fields)
    for t in txs:
        item: dict = {
            "id": t.id,
            "datetime": t.datetime.isoformat(sep=" ", timespec="seconds"),
            "account": getattr(t, "account", None),
            "amount": str(t.amount),
            "description": t.description,
        }
        # Add human-friendly account name
        try:
            acc = api.account_manager.get(getattr(t, "account", None))
            if acc is not None:
                item["account_name"] = acc.name
        except Exception:
            pass
        # Add payee id and payee name (where applicable)
        try:
            payee_id = getattr(t, "payee", None)
            if payee_id is not None:
                item["payee"] = payee_id
                p = api.payee_manager.get(payee_id)
                if p is not None:
                    item["payee_name"] = p.name
        except Exception:
            pass
        # Enrich with all known fields if requested or when fields/list-fields specified
        if need_enrich:
            item["__type__"] = type(t).__name__
            try:
                model_fields = sanitize(t.as_dict())
            except Exception:
                model_fields = {}
            # Merge, keeping the simple keys already set
            for k, v in model_fields.items():
                if k not in item:
                    item[k] = v
            # Add raw filtered columns for complete visibility
            try:
                item["__raw"] = sanitize(t.filtered())
            except Exception:
                pass
            # Add complete raw row (unfiltered) to truly show all available fields
            raw_all_sanitized = None
            try:
                raw_all = getattr(t, "_raw", None)
                if isinstance(raw_all, dict):
                    # Convert possible binary blobs to descriptive strings
                    def _blob_safe(v):
                        if isinstance(v, (bytes, bytearray, memoryview)):
                            return f"BLOB({len(v)} bytes)"
                        return v
                    raw_all_sanitized = sanitize({k: _blob_safe(v) for k, v in raw_all.items()})
                    item["__raw_all"] = raw_all_sanitized
            except Exception:
                pass
            # Do not merge raw DB columns into top-level; keep them under __raw/__raw_all
        if args.with_categories:
            cats = api.transaction_manager.category_for_transaction(t.id) or []
            item["categories"] = [{"category_id": cid, "amount": str(amt)} for cid, amt in cats]
        if args.with_tags:
            tags = api.transaction_manager.tags_for_transaction(t.id) or []
            item["tags"] = tags
        rows.append(item)

    # If only listing columns, print union of keys and exit
    if args.list_fields:
        keys = set()
        for r in rows:
            keys.update(r.keys())
        # Exclude nested raw payload key
        keys.discard("__raw")
        keys.discard("__raw_all")
        for k in sorted(keys):
            print(k)
        return 0

    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        # Determine headers
        headers = None
        if args.fields:
            headers = [h.strip() for h in args.fields.split(",") if h.strip()]
        # If --all-fields in table mode and no explicit headers, show all available top-level fields
        if args.all_fields and not headers:
            keys = set()
            for r in rows:
                keys.update(r.keys())
            # Exclude nested raw payload keys
            for k in ("__raw", "__raw_all"):
                keys.discard(k)
            # Prefer human-friendly order first, then the rest sorted
            preferred = [
                "id",
                "datetime",
                "account",
                "account_name",
                "payee",
                "payee_name",
                "amount",
                "description",
                "__type",
            ]
            remaining = [k for k in sorted(keys) if k not in preferred]
            headers = [k for k in preferred if k in keys] + remaining
        if not headers:
            headers = ["id", "datetime", "account", "account_name", "amount", "description"]
        # Pretty-print a fixed-width table that preserves empty fields
        # Build matrix of string values
        table_rows = []
        for r in rows:
            table_rows.append([str(r.get(h, "")) if r.get(h, "") is not None else "" for h in headers])

        # Compute column widths
        widths = []
        for i, h in enumerate(headers):
            col_vals = [row[i] for row in table_rows]
            max_len = max([len(h)] + [len(v) for v in col_vals])
            widths.append(max_len)

        # Helpers to render a row
        def render_row(cells):
            return "  ".join(c.ljust(w) for c, w in zip(cells, widths))

        # Print header, separator, and rows
        print(render_row(headers))
        print(render_row(["-" * len(h) for h in headers]))
        for row in table_rows:
            print(render_row(row))
        if args.with_categories:
            print("\n# categories: use --format json to see per-transaction details")
        if args.with_tags:
            print("# tags: use --format json to see per-transaction details")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
