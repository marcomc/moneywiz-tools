#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set

from moneywiz_api.moneywiz_api import MoneywizApi


def default_db() -> Path:
    return Path(
        os.path.expanduser(
            "~/Library/Containers/com.moneywiz.personalfinance-setapp/Data/Documents/.AppData/ipadMoneyWiz.sqlite"
        )
    )


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Inspect available transaction information")
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of transactions scanned (0 = all)")
    ap.add_argument("--format", choices=["table", "json"], default="table")
    args = ap.parse_args()

    api = MoneywizApi(args.db)
    txs = api.transaction_manager.get_all()
    if args.limit and args.limit > 0:
        txs = txs[-args.limit :]

    # Collect union of fields per subtype and common fields
    by_type_fields: Dict[str, Set[str]] = defaultdict(set)
    common_fields: Set[str] = set()
    first = True

    # Relationship flags
    has_categories = 0
    has_tags = 0
    has_refund_links = 0

    # Sample values for representative fields
    samples_by_type: Dict[str, Dict[str, Any]] = {}

    for t in txs:
        ttype = type(t).__name__
        rec = t.as_dict()
        keys = set(rec.keys())
        by_type_fields[ttype].update(keys)
        if first:
            common_fields = keys.copy()
            first = False
        else:
            common_fields &= keys

        # Track relationships
        if api.transaction_manager.category_for_transaction(t.id):
            has_categories += 1
        if api.transaction_manager.tags_for_transaction(t.id):
            has_tags += 1
        if ttype == "RefundTransaction":
            if api.transaction_manager.original_transaction_for_refund_transaction(t.id):
                has_refund_links += 1

        # Save sample values for first time we see a type
        if ttype not in samples_by_type:
            # add some computed/related info
            rec2 = dict(rec)
            rec2["__type__"] = ttype
            cats = api.transaction_manager.category_for_transaction(t.id)
            if cats:
                rec2["__categories__"] = [(int(c), str(a)) for (c, a) in cats]
            tags = api.transaction_manager.tags_for_transaction(t.id)
            if tags:
                rec2["__tags__"] = [int(x) for x in tags]
            if ttype == "RefundTransaction":
                orig = api.transaction_manager.original_transaction_for_refund_transaction(t.id)
                if orig:
                    rec2["__refund_original_withdraw_id__"] = int(orig)
            samples_by_type[ttype] = rec2

    # Prepare output
    if args.format == "json":
        print(
            json.dumps(
                {
                    "common_fields": sorted(common_fields),
                    "types": {k: sorted(v) for k, v in sorted(by_type_fields.items())},
                    "relationships": {
                        "has_categories_count": has_categories,
                        "has_tags_count": has_tags,
                        "has_refund_links_count": has_refund_links,
                    },
                    "samples": samples_by_type,
                },
                indent=2,
            )
        )
        return 0

    # Human-readable text
    print("== Common fields across all transactions ==")
    print(", ".join(sorted(common_fields)))
    print()

    print("== Fields by transaction type ==")
    for ttype, fields in sorted(by_type_fields.items()):
        print(f"- {ttype}:")
        print(f"  {', '.join(sorted(fields))}")
    print()

    print("== Relationship availability (counts) ==")
    print(f"- category assignments present: {has_categories}")
    print(f"- tags present: {has_tags}")
    print(f"- refund→withdraw links present: {has_refund_links}")
    print()

    print("== Sample record per type (with related info) ==")
    def _sanitize(obj: Any):
        try:
            from decimal import Decimal
        except Exception:
            Decimal = None  # type: ignore
        try:
            from datetime import datetime
        except Exception:
            datetime = None  # type: ignore
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitize(x) for x in obj]
        if Decimal is not None and isinstance(obj, Decimal):
            return str(obj)
        if datetime is not None and isinstance(obj, datetime):
            return obj.isoformat(sep=" ", timespec="seconds")
        return obj

    for ttype, sample in sorted(samples_by_type.items()):
        print(f"-- {ttype}:")
        print(json.dumps(_sanitize(sample), indent=2, sort_keys=True))
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
