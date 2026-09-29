#!/usr/bin/env python3
"""Build immutable transaction plans from explicit JSON requests."""

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
    ADJUST_BALANCE_CAPABILITY,
    DELETE_ADJUSTMENT_CAPABILITY,
    TRANSFER_CAPABILITY,
    ASSIGN_CAPABILITY,
    CREATE_OPERATION_POLICIES,
    EDIT_CAPABILITY,
    OPERATION_SCHEMA_VERSION,
    PlanValidationError,
    RECONCILE_CAPABILITIES,
    deterministic_transaction_gid,
    edit_changed_fields,
    normalize_decimal,
    transfer_postcondition,
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


def build_assign_plan(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build a guarded replacement of one transaction's owned relationships."""
    raw = _mapping(request, "request")
    if set(raw) != _ENVELOPE_FIELDS | {"operation"}:
        raise PlanValidationError("request has unknown or missing fields")
    operation = _mapping(raw.pop("operation"), "operation")
    if set(operation) != {
        "operation_id", "kind", "transaction_entity", "transaction_gid",
        "account_gid", "amount", "expected_assignments", "target", "replacement_mode",
    } or operation.get("kind") != "assign_payee_categories":
        raise PlanValidationError("operation has unknown or missing W03 fields")
    for name in ("expected_assignments", "target"):
        state = _mapping(operation[name], name)
        if set(state) != {"payee_gid", "category_splits"}:
            raise PlanValidationError(f"{name} has unknown or missing fields")
        splits = state["category_splits"]
        if not isinstance(splits, list):
            raise PlanValidationError(f"{name}.category_splits must be a list")
        normalized_splits = []
        for index, split in enumerate(splits):
            if not isinstance(split, Mapping) or set(split) != {"category_gid", "amount"}:
                raise PlanValidationError(f"{name}.category_splits[{index}] is incomplete")
            category_gid = split["category_gid"]
            if not isinstance(category_gid, str) or not category_gid.strip():
                raise PlanValidationError(f"{name}.category_splits[{index}].category_gid is invalid")
            normalized_splits.append({
                "category_gid": category_gid,
                "amount": normalize_decimal(
                    split["amount"], f"{name}.category_splits[{index}].amount"
                ),
            })
        state["category_splits"] = sorted(
            normalized_splits, key=lambda split: split["category_gid"]
        )
        operation[name] = state
    operation.update(
        capability=ASSIGN_CAPABILITY,
        owner_uri=raw["owner_uri"],
        source_event_id=raw["source_event_id"],
        currency_unit=raw["currency_unit"],
        amount=normalize_decimal(operation["amount"], "operation.amount"),
        expected_balance_delta="0",
        allowed_changed_fields=["payee", "categoriesAssigments"],
        expected_postcondition={
            **deepcopy(operation["target"]), "expected_balance_delta": "0",
        },
    )
    return validate_plan({
        "contract_version": CONTRACT_VERSION,
        "operation_schema_version": OPERATION_SCHEMA_VERSION,
        **raw,
        "capability": ASSIGN_CAPABILITY,
        "operations": [operation],
    })


def build_reconcile_plan(request: Mapping[str, Any], *, kind: str) -> dict[str, Any]:
    """Build one guarded flag transition batch from reviewed full-account scope."""
    raw = _mapping(request, "request")
    if set(raw) != _ENVELOPE_FIELDS | {"source_scope", "operations"}:
        raise PlanValidationError("request has unknown or missing W04 fields")
    scope = _mapping(raw.pop("source_scope"), "source_scope")
    requests = raw.pop("operations")
    if not isinstance(requests, list) or not requests:
        raise PlanValidationError("operations must be a nonempty list")
    capability, old, target = RECONCILE_CAPABILITIES[kind]
    operations = []
    required = {
        "operation_id", "kind", "transaction_entity", "transaction_gid",
        "account_gid", "expected_reconciled", "expected_native_status",
        "expected_native_flags", "correction_reason",
    }
    for index, value in enumerate(requests):
        operation = _mapping(value, f"operations[{index}]")
        if set(operation) != required or operation["kind"] != kind:
            raise PlanValidationError(f"operations[{index}] has unknown or missing W04 fields")
        operation.update(
            capability=capability,
            owner_uri=raw["owner_uri"],
            source_event_id=raw["source_event_id"],
            target_reconciled=target,
            expected_balance_delta="0",
            allowed_changed_fields=["reconciled"],
            expected_postcondition={
                "reconciled": target,
                "native_status": operation["expected_native_status"],
                "native_flags": operation["expected_native_flags"],
                "expected_balance_delta": "0",
            },
        )
        if operation["expected_reconciled"] is not old:
            raise PlanValidationError(f"operations[{index}] has the wrong prior state")
        operations.append(operation)
    scope["verified_balance"] = normalize_decimal(
        scope.get("verified_balance"), "source_scope.verified_balance"
    )
    return validate_plan({
        "contract_version": CONTRACT_VERSION,
        "operation_schema_version": OPERATION_SCHEMA_VERSION,
        **raw,
        "source_scope": scope,
        "capability": capability,
        "operations": operations,
    })


def build_adjust_balance_plan(request: Mapping[str, Any]) -> dict[str, Any]:
    """Plan the observed aggregate investment balance variant only."""
    raw = _mapping(request, "request")
    if set(raw) != _ENVELOPE_FIELDS | {"operation"}:
        raise PlanValidationError("request has unknown or missing W05 fields")
    operation = _mapping(raw.pop("operation"), "operation")
    if set(operation) != {
        "operation_id", "kind", "account_gid", "balance_unit",
        "expected_prior_balance", "target_balance", "occurred_at",
    } or operation.get("kind") != "adjust_investment_total":
        raise PlanValidationError("operation has unknown or missing W05 fields")
    prior = normalize_decimal(operation["expected_prior_balance"], "expected_prior_balance")
    target = normalize_decimal(operation["target_balance"], "target_balance")
    store_identity = _mapping(raw["store_identity"], "store_identity")
    operation.update(
        capability=ADJUST_BALANCE_CAPABILITY,
        transaction_entity="ReconcileTransaction",
        transaction_gid=deterministic_transaction_gid(
            store_uuid=store_identity.get("store_uuid"),
            owner_uri=raw["owner_uri"],
            source_event_id=raw["source_event_id"],
        ),
        owner_uri=raw["owner_uri"],
        source_event_id=raw["source_event_id"],
        expected_prior_balance=prior,
        target_balance=target,
        expected_balance_delta=normalize_decimal(
            format(Decimal(target) - Decimal(prior), "f"), "expected_balance_delta"
        ),
        currency_unit=raw["currency_unit"],
        timezone=raw["timezone"],
    )
    operation["expected_postcondition"] = {
        field: operation[field] for field in (
            "transaction_entity", "transaction_gid", "account_gid", "owner_uri",
            "balance_unit", "expected_prior_balance", "target_balance",
            "expected_balance_delta", "currency_unit", "occurred_at", "timezone",
        )
    }
    return validate_plan({
        "contract_version": CONTRACT_VERSION,
        "operation_schema_version": OPERATION_SCHEMA_VERSION,
        **raw,
        "capability": ADJUST_BALANCE_CAPABILITY,
        "operations": [operation],
    })


def build_delete_adjustment_plan(request: Mapping[str, Any]) -> dict[str, Any]:
    """Plan deletion of one observed latest investment-total adjustment."""
    raw = _mapping(request, "request")
    if set(raw) != _ENVELOPE_FIELDS | {"operation"}:
        raise PlanValidationError("request has unknown or missing W06 fields")
    operation = _mapping(raw.pop("operation"), "operation")
    if set(operation) != {
        "operation_id", "kind", "transaction_gid", "transaction_numeric_id",
        "account_gid", "balance_unit", "expected_amount",
        "expected_reconcile_amount", "expected_prior_balance", "occurred_at",
        "deletion_reason",
    } or operation.get("kind") != "delete_investment_total_adjustment":
        raise PlanValidationError("operation has unknown or missing W06 fields")
    amount = normalize_decimal(operation["expected_amount"], "expected_amount")
    prior = normalize_decimal(operation["expected_prior_balance"], "expected_prior_balance")
    reconcile = normalize_decimal(
        operation["expected_reconcile_amount"], "expected_reconcile_amount"
    )
    target = normalize_decimal(
        format(Decimal(prior) - Decimal(amount), "f"), "target_balance"
    )
    operation.update(
        capability=DELETE_ADJUSTMENT_CAPABILITY,
        transaction_entity="ReconcileTransaction",
        owner_uri=raw["owner_uri"],
        source_event_id=raw["source_event_id"],
        expected_amount=amount,
        expected_reconcile_amount=reconcile,
        expected_prior_balance=prior,
        target_balance=target,
        expected_balance_delta=normalize_decimal(
            format(-Decimal(amount), "f"), "expected_balance_delta"
        ),
        currency_unit=raw["currency_unit"],
        timezone=raw["timezone"],
    )
    operation["expected_postcondition"] = {
        "transaction_absent": True,
        "transaction_gid": operation["transaction_gid"],
        "account_gid": operation["account_gid"],
        "target_balance": target,
    }
    return validate_plan({
        "contract_version": CONTRACT_VERSION,
        "operation_schema_version": OPERATION_SCHEMA_VERSION,
        **raw,
        "capability": DELETE_ADJUSTMENT_CAPABILITY,
        "operations": [operation],
    })


def build_transfer_plan(request: Mapping[str, Any]) -> dict[str, Any]:
    """Plan one atomic, zero-fee replacement of imported rows with a transfer."""
    raw = _mapping(request, "request")
    if set(raw) != _ENVELOPE_FIELDS | {"destination_account", "operation"}:
        raise PlanValidationError("request has unknown or missing W07 fields")
    operation = _mapping(raw.pop("operation"), "operation")
    if set(operation) != {
        "operation_id", "kind", "source_old", "destination_old", "send_at",
        "receive_at", "sender_amount", "recipient_amount", "exchange_rate",
        "fee_amount",
    } or operation.get("kind") != "replace_import_with_transfer":
        raise PlanValidationError("operation has unknown or missing W07 fields")
    raw["destination_account"] = _mapping(raw["destination_account"], "destination_account")
    if "expected_cached_balance" in raw["destination_account"]:
        raw["destination_account"]["expected_cached_balance"] = normalize_decimal(
            raw["destination_account"]["expected_cached_balance"],
            "destination_account.expected_cached_balance",
        )
    for name in ("source_old", "destination_old"):
        if operation[name] is None:
            continue
        row = _mapping(operation[name], name)
        if "amount" in row:
            row["amount"] = normalize_decimal(row["amount"], f"{name}.amount")
        operation[name] = row
    for name in ("sender_amount", "recipient_amount", "exchange_rate", "fee_amount"):
        operation[name] = normalize_decimal(operation[name], name)
    store = _mapping(raw["store_identity"], "store_identity")
    operation.update(
        capability=TRANSFER_CAPABILITY,
        transaction_entity="TransferWithdrawTransaction",
        transaction_gid=deterministic_transaction_gid(
            store_uuid=store.get("store_uuid"), owner_uri=raw["owner_uri"],
            source_event_id=raw["source_event_id"] + ":withdraw",
        ),
        recipient_transaction_gid=deterministic_transaction_gid(
            store_uuid=store.get("store_uuid"), owner_uri=raw["owner_uri"],
            source_event_id=raw["source_event_id"] + ":deposit",
        ),
        owner_uri=raw["owner_uri"],
        source_event_id=raw["source_event_id"],
    )
    plan = {
        "contract_version": CONTRACT_VERSION,
        "operation_schema_version": OPERATION_SCHEMA_VERSION,
        **raw,
        "capability": TRANSFER_CAPABILITY,
        "operations": [operation],
    }
    operation["expected_postcondition"] = transfer_postcondition(plan, operation)
    return validate_plan(plan)


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
    for name in ("create", "edit", "assign", "reconcile", "unreconcile", "adjust-balance", "delete-adjustment", "transfer"):
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
        builders = {"create": build_plan, "edit": build_edit_plan,
                    "assign": build_assign_plan, "adjust-balance": build_adjust_balance_plan,
                    "delete-adjustment": build_delete_adjustment_plan,
                    "transfer": build_transfer_plan}
        request = _load_request(args.request)
        plan = (builders[args.command](request)
                if args.command in builders else build_reconcile_plan(
                    request, kind=f"{args.command}_transaction"))
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
