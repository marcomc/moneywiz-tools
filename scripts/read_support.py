"""Shared read completeness and absolute-time semantics for CLI consumers."""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)


def json_value(value):
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite decimal in read result")
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite float in read result")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"binary_bytes": len(value)}
    return value


def cached_balance_value(value):
    """Render a selected native cached balance without coercing its raw type."""
    if value is None:
        return None
    if type(value) not in (int, float):
        raise TypeError("cached account balance is not numeric")
    if type(value) is float and not math.isfinite(value):
        raise ValueError("cached account balance is not finite")
    return str(value)


def transaction_description(record) -> str | None:
    """Preserve a nullable native description while rejecting other raw types."""
    try:
        raw_description = record._raw["ZDESC2"]
        description = record.description
    except (AttributeError, KeyError, TypeError) as exc:
        raise TypeError("transaction description is not native text") from exc
    if raw_description is None and description is None:
        return None
    if type(raw_description) is not str or type(description) is not str:
        raise TypeError("transaction description is not native text")
    return description


def native_transaction_integer(record, column: str) -> int:
    """Require an exported raw transaction field to retain SQLite integer type."""
    try:
        value = record._raw[column]
    except (AttributeError, KeyError, TypeError) as exc:
        raise TypeError("native transaction metadata is not an integer") from exc
    if type(value) is not int:
        raise TypeError("native transaction metadata is not an integer")
    return value


def native_account_integer(record, column: str) -> int:
    """Require an exported raw account field to retain SQLite integer type."""
    try:
        value = record._raw[column]
    except (AttributeError, KeyError, TypeError) as exc:
        raise TypeError("native account metadata is not an integer") from exc
    if type(value) is not int:
        raise TypeError("native account metadata is not an integer")
    return value


def transaction_time(record) -> datetime:
    """Read Core Data absolute seconds; do not inherit legacy local epoch offsets."""
    seconds = record._raw.get("ZDATE1")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise TypeError("transaction date is not a numeric Core Data timestamp")
    if not math.isfinite(seconds):
        raise ValueError("transaction date is not finite")
    return APPLE_EPOCH + timedelta(seconds=seconds)


def cutoff(value: str | None, zone_name: str = "UTC") -> tuple[datetime, bool]:
    """Return an inclusive UTC boundary; a date means local midnight."""
    zone = ZoneInfo(zone_name)
    if value is None:
        return datetime.now(UTC), False
    if len(value) == 10:
        day = date.fromisoformat(value)
        if day == date.max:
            raise ValueError("date cutoff exceeds the supported range")
        boundary = datetime.combine(day, time(), tzinfo=zone)
        return boundary.astimezone(UTC), False
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp cutoff requires an explicit UTC offset")
    return parsed.astimezone(UTC), False


def _selected_transactions(
    api,
    account: int | None,
    until: str | None,
    zone: str,
    *,
    include_accountless: bool,
    resolved_cutoff: tuple[datetime, bool] | None = None,
):
    boundary, exclusive = resolved_cutoff or cutoff(until, zone)
    records = []
    for record in api.transaction_manager.records().values():
        if not hasattr(record, "account") and (
            not include_accountless or account is not None
        ):
            continue
        if account is not None and record.account != account:
            continue
        instant = transaction_time(record)
        if instant < boundary or (not exclusive and instant == boundary):
            records.append(record)
    return sorted(records, key=lambda record: (transaction_time(record), record.id))


def selected_transactions(
    api,
    account: int | None,
    until: str | None,
    zone: str,
    *,
    resolved_cutoff: tuple[datetime, bool] | None = None,
):
    """Select account-backed rows for the transaction-list command."""
    return _selected_transactions(
        api,
        account,
        until,
        zone,
        include_accountless=False,
        resolved_cutoff=resolved_cutoff,
    )


def selected_snapshot_transactions(
    api,
    account: int | None,
    until: str | None,
    zone: str,
    *,
    resolved_cutoff: tuple[datetime, bool] | None = None,
):
    """Preserve every parsed row when the snapshot scope is unfiltered."""
    return _selected_transactions(
        api,
        account,
        until,
        zone,
        include_accountless=True,
        resolved_cutoff=resolved_cutoff,
    )


def validate_selected_account(api, account_id: int | None, report: dict | None = None):
    """Reject an absent account while retaining observed unreadable diagnostics."""
    if account_id is None or account_id in api.account_manager.records():
        return
    completeness = report or api.completeness().as_dict()
    account_report = completeness["managers"]["accounts"]
    observed_ids = {
        record_id
        for record_id in account_report.get("source_ids", [])
        if type(record_id) is int
    }
    observed_ids.update(
        skipped.get("record_id")
        for skipped in account_report.get("skipped", [])
        if type(skipped.get("record_id")) is int
    )
    if account_id not in observed_ids:
        raise ValueError("requested account does not exist")


def report_completeness(api, *, enrichment_errors: list[dict] | None = None):
    report = api.completeness().as_dict()
    if enrichment_errors:
        report["complete"] = False
        report["status"] = "partial"
        report["enrichment_errors"] = enrichment_errors
    if not report["complete"]:
        summary = {
            **report,
            "managers": {
                name: {
                    key: value
                    for key, value in manager.items()
                    if key not in {"source_ids", "parsed_ids"}
                }
                for name, manager in report["managers"].items()
            },
        }
        print(json.dumps({"read_completeness": summary}), file=sys.stderr)
    return report, 0 if report["complete"] else 3


def run_read_command(main) -> int:
    """Bound failures without accidentally serializing financial row values."""
    try:
        return main()
    except (
        OSError,
        OverflowError,
        ValueError,
        TypeError,
        KeyError,
        sqlite3.Error,
        ZoneInfoNotFoundError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": type(exc).__name__,
                    "message": "Read failed; check database, schema and command arguments",
                }
            ),
            file=sys.stderr,
        )
        return 2
