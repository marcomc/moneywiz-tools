from __future__ import annotations

import argparse
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from moneywiz_api.moneywiz_api import MoneywizApi
from read_support import (
    json_value,
    report_completeness,
    run_read_command,
    selected_transactions,
    transaction_description,
    transaction_time,
    validate_selected_account,
)


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="List MoneyWiz transactions for an account"
    )
    ap.add_argument(
        "--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB"
    )
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
    ap.add_argument(
        "--until",
        type=str,
        help="Inclusive local-midnight date or offset-qualified timestamp",
    )
    ap.add_argument(
        "--timezone",
        default="UTC",
        help="IANA timezone for date cutoff and output (default UTC)",
    )
    ap.add_argument(
        "--diagnostics",
        action="store_true",
        help="Wrap JSON rows with completeness metadata",
    )
    ap.add_argument(
        "--with-categories", action="store_true", help="Include category assignments"
    )
    ap.add_argument(
        "--with-tags", action="store_true", help="Include tags for each transaction"
    )
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
    if args.diagnostics and (args.format != "json" or args.list_fields):
        ap.error("--diagnostics requires --format json without --list-fields")

    api = MoneywizApi(args.db, managers=("accounts", "transactions", "payees"))
    validate_selected_account(api, args.account)
    txs = selected_transactions(api, args.account, args.until, args.timezone)
    # Sort newest first and apply optional limit (0 or negative means no limit)
    txs = list(reversed(txs))
    if args.limit and args.limit > 0:
        txs = txs[: args.limit]

    sanitize = json_value

    rows: list[dict] = []
    enrichment_errors = []
    need_enrich = bool(args.all_fields or args.fields or args.list_fields)
    for t in txs:
        item: dict = {
            "id": t.id,
            "datetime": transaction_time(t)
            .astimezone(ZoneInfo(args.timezone))
            .isoformat(timespec="seconds"),
            "account": getattr(t, "account", None),
            "amount": json_value(t.amount),
            "description": transaction_description(t),
        }
        # Add human-friendly account name
        try:
            acc = api.account_manager.get(getattr(t, "account", None))
            if acc is not None:
                item["account_name"] = acc.name
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            enrichment_errors.append(
                {"id": t.id, "field": "account_name", "error": type(exc).__name__}
            )
        # Add payee id and payee name (where applicable)
        try:
            payee_id = getattr(t, "payee", None)
            if payee_id is not None:
                item["payee"] = payee_id
                p = api.payee_manager.get(payee_id)
                if p is not None:
                    item["payee_name"] = p.name
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            enrichment_errors.append(
                {"id": t.id, "field": "payee_name", "error": type(exc).__name__}
            )
        # Enrich with all known fields if requested or when fields/list-fields specified
        if need_enrich:
            item["__type__"] = type(t).__name__
            try:
                model_fields = sanitize(t.as_dict())
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                enrichment_errors.append(
                    {"id": t.id, "field": "model_fields", "error": type(exc).__name__}
                )
                model_fields = {}
            # Merge, keeping the simple keys already set
            for k, v in model_fields.items():
                if k not in item:
                    item[k] = v
            # Add raw filtered columns for complete visibility
            try:
                item["__raw"] = sanitize(t.filtered())
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                enrichment_errors.append(
                    {"id": t.id, "field": "raw", "error": type(exc).__name__}
                )
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

                    raw_all_sanitized = sanitize(
                        {k: _blob_safe(v) for k, v in raw_all.items()}
                    )
                    item["__raw_all"] = raw_all_sanitized
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                enrichment_errors.append(
                    {"id": t.id, "field": "raw_all", "error": type(exc).__name__}
                )
            # Do not merge raw DB columns into top-level; keep them under __raw/__raw_all
        if args.with_categories:
            cats = api.transaction_manager.category_for_transaction(t.id) or []
            item["categories"] = [
                {"category_id": cid, "amount": json_value(amt)} for cid, amt in cats
            ]
        if args.with_tags:
            tags = api.transaction_manager.tags_for_transaction(t.id) or []
            item["tags"] = tags
        rows.append(item)

    report, status = report_completeness(api, enrichment_errors=enrichment_errors)
    api.close()

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
        return status

    if args.format == "json":
        print(
            json.dumps(
                {"rows": rows, "completeness": report} if args.diagnostics else rows,
                indent=2,
                allow_nan=False,
            )
        )
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
            headers = [
                "id",
                "datetime",
                "account",
                "account_name",
                "amount",
                "description",
            ]
        # Pretty-print a fixed-width table that preserves empty fields
        # Build matrix of string values
        table_rows = []
        for r in rows:
            table_rows.append(
                [str(r.get(h, "")) if r.get(h, "") is not None else "" for h in headers]
            )

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
    return status


if __name__ == "__main__":
    raise SystemExit(run_read_command(main))
