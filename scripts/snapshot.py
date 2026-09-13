"""Export a complete read graph and bounded audits for reconciliation planning."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from moneywiz_api.moneywiz_api import MoneywizApi
from read_support import (
    cached_balance_value,
    cutoff,
    json_value,
    native_transaction_integer,
    run_read_command,
    selected_snapshot_transactions,
    transaction_description,
    transaction_time,
)

ACCOUNTLESS_TRANSACTION_ENTITIES = frozenset({"TransferBudgetTransaction"})


def record_view(record) -> dict:
    result = json_value(record.as_dict())
    result["entity"] = type(record).__name__
    return result


def audit_graph(
    accounts: list[dict],
    transactions: list[dict],
    transaction_report: dict | None = None,
) -> list[dict]:
    """Find structural defects and non-authoritative duplicate candidates."""
    findings = []
    transaction_report = transaction_report or {}
    source_ids = {
        record_id
        for record_id in transaction_report.get("source_ids", [])
        if type(record_id) is int
    }
    parsed_ids = {
        record_id
        for record_id in transaction_report.get("parsed_ids", [])
        if type(record_id) is int
    }
    skipped_ids = {
        skipped.get("record_id")
        for skipped in transaction_report.get("skipped", [])
        if type(skipped.get("record_id")) is int
    }
    unreadable_ids = (source_ids - parsed_ids) | skipped_ids
    account_map = {}
    for row in accounts:
        account_id = _audit_scalar(row, "id")
        _audit_scalar(row, "user", required=False)
        account_map[account_id] = row
    transaction_map = {_audit_scalar(row, "id"): row for row in transactions}
    candidates = defaultdict(list)
    for row in transactions:
        record_id = _audit_scalar(row, "id")
        entity = _audit_scalar(row, "entity")
        account_id = _audit_scalar(row, "account", required=False)
        account = account_map.get(account_id)
        if account_id is None:
            if entity not in ACCOUNTLESS_TRANSACTION_ENTITIES:
                findings.append({"kind": "missing_account", "ids": [record_id]})
        elif account is None:
            findings.append({"kind": "missing_account", "ids": [record_id]})
        key = (
            account_id,
            _audit_scalar(row, "amount", required=False),
            _audit_scalar(row, "datetime", required=False),
            _audit_scalar(row, "description", required=False),
            entity,
        )
        candidates[key].append(record_id)
        send = entity == "TransferWithdrawTransaction"
        receive = entity == "TransferDepositTransaction"
        if not send and not receive:
            continue
        paired_id = _audit_scalar(
            row,
            "recipient_transaction" if send else "sender_transaction",
            required=False,
        )
        paired = transaction_map.get(paired_id)
        if paired is None:
            findings.append(
                {
                    "kind": (
                        "unreadable_transfer_leg"
                        if paired_id in unreadable_ids
                        else "missing_transfer_leg"
                    ),
                    "ids": [record_id],
                    "related_id": paired_id,
                }
            )
            continue
        reverse_key = "sender_transaction" if send else "recipient_transaction"
        expected_entity = (
            "TransferDepositTransaction" if send else "TransferWithdrawTransaction"
        )
        target_account = _audit_scalar(
            row, "recipient_account" if send else "sender_account", required=False
        )
        reverse_id = _audit_scalar(paired, reverse_key, required=False)
        paired_entity = _audit_scalar(paired, "entity")
        paired_account_id = _audit_scalar(paired, "account", required=False)
        reverse_account = _audit_scalar(
            paired,
            "sender_account" if send else "recipient_account",
            required=False,
        )
        if (
            reverse_id != record_id
            or paired_entity != expected_entity
            or paired_account_id != target_account
            or reverse_account != account_id
        ):
            findings.append(
                {"kind": "nonreciprocal_transfer", "ids": [record_id, paired_id]}
            )
            continue
        if not send:
            continue
        paired_account = account_map.get(paired_account_id)
        if (
            account
            and paired_account
            and account.get("user") != paired_account.get("user")
        ):
            findings.append(
                {"kind": "cross_owner_transfer", "ids": [record_id, paired_id]}
            )
        if not _transfer_fx_matches(row, paired):
            findings.append(
                {"kind": "mismatched_transfer_fx", "ids": [record_id, paired_id]}
            )
        paired_datetime = _audit_scalar(paired, "datetime", required=False)
        if key[2] != paired_datetime:
            findings.append(
                {
                    "kind": "different_transfer_dates",
                    "severity": "candidate",
                    "ids": [record_id, paired_id],
                }
            )
        reconciled = _audit_scalar(row, "reconciled", required=False)
        paired_reconciled = _audit_scalar(paired, "reconciled", required=False)
        if not (reconciled and paired_reconciled):
            findings.append(
                {
                    "kind": "unreconciled_transfer_legs",
                    "severity": "candidate",
                    "ids": [record_id, paired_id],
                }
            )
    for ids in candidates.values():
        if len(ids) > 1:
            findings.append(
                {"kind": "coincident_transactions", "severity": "candidate", "ids": ids}
            )
    return findings


def _audit_scalar(row: dict, key: str, *, required: bool = True):
    if required and key not in row:
        raise ValueError("graph audit input is missing a required field")
    value = row.get(key)
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise TypeError("graph audit input contains a non-scalar field")
    return value


def _audit_decimal(row: dict, key: str) -> Decimal:
    value = _audit_scalar(row, key)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("graph audit input contains an invalid numeric field") from exc


def _audit_optional_decimal(row: dict, key: str) -> Decimal:
    value = _audit_scalar(row, key, required=False)
    if value is None:
        return Decimal(0)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("graph audit input contains an invalid numeric field") from exc


def _transfer_fx_matches(withdrawal: dict, deposit: dict) -> bool:
    deposit_recipient_amount = _audit_decimal(
        deposit, "original_amount"
    ) + _audit_optional_decimal(deposit, "original_fee")
    return (
        _audit_decimal(withdrawal, "original_amount")
        == _audit_decimal(deposit, "sender_amount")
        and _audit_scalar(withdrawal, "original_currency")
        == _audit_scalar(deposit, "sender_currency")
        and _audit_decimal(withdrawal, "recipient_amount") == deposit_recipient_amount
        and _audit_scalar(withdrawal, "recipient_currency")
        == _audit_scalar(deposit, "original_currency")
        and _audit_decimal(withdrawal, "original_exchange_rate")
        == _audit_decimal(deposit, "original_exchange_rate")
    )


def build_snapshot(api, account: int | None, until: str | None, zone: str) -> dict:
    boundary, exclusive = cutoff(until, zone)
    completeness = api.completeness().as_dict()
    all_accounts = [
        record_view(record) for record in api.account_manager.records().values()
    ]
    if account is not None and account not in api.account_manager.records():
        raise ValueError("requested account is missing or unreadable")
    # Audit the loaded graph before cutoff/account filtering, so an out-of-scope
    # counterpart is not incorrectly described as an orphan.
    all_transactions = []
    for record in api.transaction_manager.records().values():
        description = transaction_description(record)
        row = record_view(record)
        row["description"] = description
        row["datetime"] = (
            transaction_time(record).astimezone(ZoneInfo(zone)).isoformat()
        )
        row["categories"] = [
            {"category_id": category, "amount": json_value(amount)}
            for category, amount in api.transaction_manager.category_for_transaction(
                record.id
            )
            or []
        ]
        row["tags"] = api.transaction_manager.tags_for_transaction(record.id) or []
        row["original_transaction"] = (
            api.transaction_manager.original_transaction_for_refund_transaction(
                record.id
            )
        )
        # Preserve raw native status; interpreting cleared/pending requires a
        # separately established entity/version contract.
        row["native_status"] = native_transaction_integer(record, "ZSTATUS1")
        row["native_flags"] = native_transaction_integer(record, "ZFLAGS1")
        all_transactions.append(row)
    selected = {
        record.id
        for record in selected_snapshot_transactions(
            api, account, until, zone, resolved_cutoff=(boundary, exclusive)
        )
    }
    transactions = [row for row in all_transactions if row["id"] in selected]
    accounts = [row for row in all_accounts if account is None or row["id"] == account]
    for row in accounts:
        raw = api.account_manager.get(row["id"])._raw
        value = raw.get("ZBALLANCE")
        row["recorded_balance"] = cached_balance_value(value)
        row["balance_basis"] = "native_cached_value_not_source_verified"
        row["archived"] = raw.get("ZARCHIVED")
    holdings = [
        record_view(record)
        for record in api.investment_holding_manager.records().values()
        if account is None or record.account == account
    ]
    findings = [
        finding
        for finding in audit_graph(
            all_accounts,
            all_transactions,
            completeness["managers"]["transactions"],
        )
        if account is None or any(record_id in selected for record_id in finding["ids"])
    ]
    return {
        "format_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "account": account,
            "timezone": zone,
            "cutoff": boundary.isoformat(),
            "cutoff_exclusive": exclusive,
            "graph_audit": "all_loaded_records",
            "completeness": "all_loaded_managers",
        },
        "completeness": completeness,
        "read_schema_profile": asdict(api.accessor.schema_profile),
        "accounts": accounts,
        "transactions": transactions,
        "holdings": holdings,
        "payees": [
            record_view(record) for record in api.payee_manager.records().values()
        ],
        "categories": [
            record_view(record) for record in api.category_manager.records().values()
        ],
        "tags": [record_view(record) for record in api.tag_manager.records().values()],
        "audit": findings,
        "source_coverage": "not_verified",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export reconciliation snapshot and graph diagnostics"
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--account", type=int)
    parser.add_argument(
        "--until", help="Inclusive local-midnight date or offset-qualified timestamp"
    )
    parser.add_argument(
        "--timezone", default="UTC", help="IANA timezone for dates/output (default UTC)"
    )
    args = parser.parse_args()

    def execute() -> int:
        cutoff(args.until, args.timezone)
        with MoneywizApi(args.db) as api:
            result = build_snapshot(api, args.account, args.until, args.timezone)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0 if result["completeness"]["complete"] else 3

    return run_read_command(execute)


if __name__ == "__main__":
    raise SystemExit(main())
