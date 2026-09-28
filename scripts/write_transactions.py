#!/usr/bin/env python3
"""Build immutable W01 creation and W02 edit plans from explicit JSON requests."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

from write_plan import (
    CONTRACT_VERSION,
    CREATE_OPERATION_POLICIES,
    EDIT_CAPABILITY,
    OPERATION_SCHEMA_VERSION,
    PlanValidationError,
    deterministic_transaction_gid,
    edit_changed_fields,
    normalize_decimal,
    validate_plan,
)

_ENVELOPE_FIELDS = {
    "plan_id",
    "profile_id",
    "model_checksum",
    "store_identity",
    "owner_uri",
    "app_identity",
    "created_at",
    "timezone",
    "source_interval",
    "source_evidence_refs",
    "source_event_id",
    "expected_account_gid",
    "expected_cached_account_balance",
    "currency_unit",
}
_OPERATION_FIELDS = {
    "operation_id",
    "kind",
    "account_gid",
    "amount",
    "occurred_at",
    "payee_gid",
    "category_splits",
    "tag_gids",
    "note",
    "refund_reference",
}


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PlanValidationError(f"{field} must be a JSON object")
    return deepcopy(dict(value))


def build_plan(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build and validate one deterministic W01 plan without opening a store."""
    raw = _mapping(request, "request")
    if set(raw) != _ENVELOPE_FIELDS | {"operation"}:
        raise PlanValidationError("request has unknown or missing fields")
    operation_request = _mapping(raw.pop("operation"), "operation")
    if set(operation_request) != _OPERATION_FIELDS:
        raise PlanValidationError("operation has unknown or missing fields")
    kind = operation_request["kind"]
    if kind not in CREATE_OPERATION_POLICIES:
        raise PlanValidationError("operation.kind is not a supported W01 kind")
    capability, transaction_entity, _sign = CREATE_OPERATION_POLICIES[kind]
    store_identity = raw.get("store_identity")
    if not isinstance(store_identity, Mapping):
        raise PlanValidationError("store_identity must be a JSON object")
    transaction_gid = deterministic_transaction_gid(
        store_uuid=store_identity.get("store_uuid"),
        owner_uri=raw.get("owner_uri"),
        source_event_id=raw.get("source_event_id"),
    )
    amount = normalize_decimal(operation_request["amount"], "operation.amount")
    category_splits = operation_request["category_splits"]
    if isinstance(category_splits, list):
        normalized_splits = []
        for index, split in enumerate(category_splits):
            if isinstance(split, Mapping) and "amount" in split:
                split = deepcopy(dict(split))
                split["amount"] = normalize_decimal(
                    split["amount"], f"operation.category_splits[{index}].amount"
                )
            normalized_splits.append(split)
        category_splits = sorted(
            normalized_splits,
            key=lambda split: (
                split.get("category_gid", "") if isinstance(split, Mapping) else ""
            ),
        )
    operation = {
        "operation_id": operation_request["operation_id"],
        "kind": kind,
        "capability": capability,
        "transaction_entity": transaction_entity,
        "transaction_gid": transaction_gid,
        "account_gid": operation_request["account_gid"],
        "owner_uri": raw["owner_uri"],
        "source_event_id": raw["source_event_id"],
        "amount": amount,
        "currency_unit": raw["currency_unit"],
        "occurred_at": operation_request["occurred_at"],
        "timezone": raw["timezone"],
        "payee_gid": operation_request["payee_gid"],
        "category_splits": category_splits,
        "tag_gids": sorted(operation_request["tag_gids"])
        if isinstance(operation_request["tag_gids"], list)
        and all(isinstance(tag, str) for tag in operation_request["tag_gids"])
        else operation_request["tag_gids"],
        "note": operation_request["note"],
        "refund_reference": operation_request["refund_reference"],
        "expected_balance_delta": amount,
    }
    operation["expected_postcondition"] = {
        field: deepcopy(operation[field])
        for field in (
            "transaction_entity",
            "transaction_gid",
            "account_gid",
            "owner_uri",
            "amount",
            "currency_unit",
            "occurred_at",
            "timezone",
            "payee_gid",
            "category_splits",
            "tag_gids",
            "note",
            "refund_reference",
            "expected_balance_delta",
        )
    }
    return validate_plan(
        {
            "contract_version": CONTRACT_VERSION,
            "operation_schema_version": OPERATION_SCHEMA_VERSION,
            **raw,
            "capability": capability,
            "operations": [operation],
        }
    )


def build_edit_plan(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build a guarded scalar edit without discovering or opening any store."""
    raw = _mapping(request, "request")
    if set(raw) != _ENVELOPE_FIELDS | {"operation"}:
        raise PlanValidationError("request has unknown or missing fields")
    operation = _mapping(raw.pop("operation"), "operation")
    if (
        set(operation)
        != {
            "operation_id",
            "kind",
            "transaction_entity",
            "transaction_gid",
            "account_gid",
            "changes",
            "expected_prior",
            "correction_mode",
        }
        or operation.get("kind") != "edit_transaction"
    ):
        raise PlanValidationError("operation has unknown or missing W02 fields")
    changes = _mapping(operation["changes"], "changes")
    prior = _mapping(operation["expected_prior"], "expected_prior")
    allowed = edit_changed_fields(changes)
    if set(changes) != set(prior):
        raise PlanValidationError(
            "expected_prior must cover exactly every changed field"
        )
    delta = "0"
    if "amount" in changes:
        changes["amount"] = normalize_decimal(changes["amount"], "changes.amount")
        prior["amount"] = normalize_decimal(prior["amount"], "expected_prior.amount")
        delta = normalize_decimal(
            format(Decimal(changes["amount"]) - Decimal(prior["amount"]), "f"),
            "expected_balance_delta",
        )
    operation.update(
        changes=changes,
        expected_prior=prior,
        capability=EDIT_CAPABILITY,
        owner_uri=raw["owner_uri"],
        source_event_id=raw["source_event_id"],
        currency_unit=raw["currency_unit"],
        timezone=raw["timezone"],
        allowed_changed_fields=allowed,
        expected_balance_delta=delta,
        expected_postcondition={
            "fields": deepcopy(changes),
            "expected_balance_delta": delta,
        },
    )
    return validate_plan(
        {
            "contract_version": CONTRACT_VERSION,
            "operation_schema_version": OPERATION_SCHEMA_VERSION,
            **raw,
            "capability": EDIT_CAPABILITY,
            "operations": [operation],
        }
    )


def _load_request(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanValidationError(f"cannot load request: {exc}") from exc
    return _mapping(payload, "request")


def _write_plan(path: Path, plan: dict[str, Any]) -> None:
    target = path.expanduser()
    if not target.is_absolute():
        target = Path.cwd() / target
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    created = False
    try:
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        created = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
    except OSError as exc:
        if created:
            target.unlink(missing_ok=True)
        raise PlanValidationError(f"cannot create immutable plan: {exc}") from exc


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        help=argparse.SUPPRESS,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "edit"):
        command = commands.add_parser(name)
        command.add_argument("--request", type=Path, required=True)
        command.add_argument(
            "--plan",
            type=Path,
            help="Create the immutable plan at this new path; otherwise print it",
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        builder = build_edit_plan if args.command == "edit" else build_plan
        plan = builder(_load_request(args.request))
        if args.plan is not None:
            _write_plan(args.plan, plan)
            output = {
                "status": "planned",
                "plan": str(args.plan.expanduser().resolve()),
                "plan_digest": plan["plan_digest"],
            }
        else:
            output = {"status": "planned", "plan": plan}
        print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (PlanValidationError, OSError) as exc:
        print(
            json.dumps(
                {"status": "error", "error": type(exc).__name__, "message": str(exc)}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
