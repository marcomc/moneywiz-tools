"""Strict, versioned plans for the P1F Core Data writer bridge."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, NotRequired, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CONTRACT_VERSION = 2
OPERATION_SCHEMA_VERSION = 1
PAYEE_CAPABILITY = "write.reassign-payees-by-id"
_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_ENTITIES = {
    "DepositTransaction",
    "InvestmentExchangeTransaction",
    "InvestmentBuyTransaction",
    "InvestmentSellTransaction",
    "ReconcileTransaction",
    "RefundTransaction",
    "TransferBudgetTransaction",
    "TransferDepositTransaction",
    "TransferWithdrawTransaction",
    "WithdrawTransaction",
}


class PlanValidationError(ValueError):
    """Raised when a plan cannot safely reach the native writer."""


class PayeeReassignmentOperation(TypedDict):
    """The only enabled operation schema in the P1F bridge."""

    operation_id: str
    kind: str
    capability: str
    transaction_entity: str
    transaction_gid: str
    expected_old_payee_gid: str | None
    target_payee_gid: str
    owner_uri: str
    source_event_id: str
    expected_postcondition: dict[str, str]
    allowed_changed_fields: list[str]


class WritePlan(TypedDict):
    """Version-two envelope, intentionally closed until W01-W04 are evidenced."""

    contract_version: int
    operation_schema_version: int
    plan_id: str
    plan_digest: NotRequired[str]
    profile_id: str
    model_checksum: str
    store_identity: dict[str, str]
    owner_uri: str
    app_identity: dict[str, str]
    created_at: str
    timezone: str
    source_interval: dict[str, str]
    source_evidence_refs: list[str]
    capability: str
    source_event_id: str
    expected_account_gid: str
    expected_cached_account_balance: str
    currency_unit: str
    operations: list[PayeeReassignmentOperation]


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Return the cross-language canonical JSON used by the plan digest."""
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def compute_digest(payload: Mapping[str, Any]) -> str:
    """Hash a plan after excluding its self-referential digest field."""
    canonical_payload = deepcopy(dict(payload))
    canonical_payload.pop("plan_digest", None)
    return hashlib.sha256(canonical_json(canonical_payload).encode("utf-8")).hexdigest()


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise PlanValidationError(f"{field} must be a nonblank, trimmed string")
    return value


def _decimal(value: object, field: str) -> str:
    value = _text(value, field)
    if not _DECIMAL.fullmatch(value):
        raise PlanValidationError(f"{field} must be a plain decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise PlanValidationError(f"{field} must be a decimal string") from exc
    if not parsed.is_finite():
        raise PlanValidationError(f"{field} must be finite")
    converted = float(parsed)
    if not math.isfinite(converted) or Decimal(str(converted)) != parsed:
        raise PlanValidationError(f"{field} cannot round-trip through native Double")
    return value


def _timestamp(value: object, field: str) -> str:
    value = _text(value, field)
    if not _TIMESTAMP.fullmatch(value):
        raise PlanValidationError(
            f"{field} must be ISO-8601 with seconds and an offset"
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PlanValidationError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PlanValidationError(f"{field} must include an offset")
    return value


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise PlanValidationError(f"{field} must be a nonempty list")
    return [_text(item, f"{field}[]") for item in value]


def validate_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the complete P1F envelope and reject unverified future writes."""
    if not isinstance(payload, Mapping):
        raise PlanValidationError("plan must be a JSON object")
    plan = deepcopy(dict(payload))
    required = {
        "contract_version",
        "operation_schema_version",
        "plan_id",
        "plan_digest",
        "profile_id",
        "model_checksum",
        "store_identity",
        "owner_uri",
        "app_identity",
        "created_at",
        "timezone",
        "source_interval",
        "source_evidence_refs",
        "capability",
        "source_event_id",
        "expected_account_gid",
        "expected_cached_account_balance",
        "currency_unit",
        "operations",
    }
    if set(plan) != required and set(plan) != required - {"plan_digest"}:
        raise PlanValidationError("plan has unknown or missing fields")
    if (
        type(plan.get("contract_version")) is not int
        or plan.get("contract_version") != CONTRACT_VERSION
    ):
        raise PlanValidationError("unsupported contract_version")
    if (
        type(plan.get("operation_schema_version")) is not int
        or plan.get("operation_schema_version") != OPERATION_SCHEMA_VERSION
    ):
        raise PlanValidationError("unsupported operation_schema_version")
    for field in (
        "plan_id",
        "profile_id",
        "model_checksum",
        "owner_uri",
        "source_event_id",
    ):
        _text(plan.get(field), field)
    _timestamp(plan.get("created_at"), "created_at")
    timezone = _text(plan.get("timezone"), "timezone")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise PlanValidationError("timezone must be an IANA timezone") from exc
    if plan.get("capability") != PAYEE_CAPABILITY:
        raise PlanValidationError("capability is not enabled by P1F")
    store = plan.get("store_identity")
    if not isinstance(store, Mapping):
        raise PlanValidationError("store_identity must be an object")
    _text(store.get("store_uuid"), "store_identity.store_uuid")
    if set(store) != {"store_uuid"}:
        raise PlanValidationError("store_identity has unknown or missing fields")
    app = plan.get("app_identity")
    if not isinstance(app, Mapping):
        raise PlanValidationError("app_identity must be an object")
    for field in ("bundle_id", "version", "path", "model_path"):
        _text(app.get(field), f"app_identity.{field}")
    if set(app) != {"bundle_id", "version", "path", "model_path"}:
        raise PlanValidationError("app_identity has unknown or missing fields")
    interval = plan.get("source_interval")
    if not isinstance(interval, Mapping):
        raise PlanValidationError("source_interval must be an object")
    _timestamp(interval.get("start"), "source_interval.start")
    _timestamp(interval.get("end"), "source_interval.end")
    if set(interval) != {"start", "end"}:
        raise PlanValidationError("source_interval has unknown or missing fields")
    if datetime.fromisoformat(interval["start"]) > datetime.fromisoformat(
        interval["end"]
    ):
        raise PlanValidationError(
            "source_interval.start must not be after source_interval.end"
        )
    _string_list(plan.get("source_evidence_refs"), "source_evidence_refs")
    _text(plan.get("expected_account_gid"), "expected_account_gid")
    _decimal(
        plan.get("expected_cached_account_balance"), "expected_cached_account_balance"
    )
    _text(plan.get("currency_unit"), "currency_unit")
    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        raise PlanValidationError("operations must be a nonempty list")
    operation_ids: set[str] = set()
    transaction_gids: set[str] = set()
    for index, operation in enumerate(operations):
        prefix = f"operations[{index}]"
        if not isinstance(operation, Mapping):
            raise PlanValidationError(f"{prefix} must be an object")
        expected_keys = {
            "operation_id",
            "kind",
            "capability",
            "transaction_entity",
            "transaction_gid",
            "expected_old_payee_gid",
            "target_payee_gid",
            "owner_uri",
            "source_event_id",
            "expected_postcondition",
            "allowed_changed_fields",
        }
        if set(operation) != expected_keys:
            raise PlanValidationError(f"{prefix} has unknown or missing fields")
        operation_id = _text(operation.get("operation_id"), f"{prefix}.operation_id")
        if operation_id in operation_ids:
            raise PlanValidationError("operation_id values must be unique")
        operation_ids.add(operation_id)
        if operation.get("kind") != "reassign_payee":
            raise PlanValidationError(f"{prefix}.kind is not enabled by P1F")
        if operation.get("capability") != PAYEE_CAPABILITY:
            raise PlanValidationError(f"{prefix}.capability is not enabled by P1F")
        for field in (
            "transaction_entity",
            "transaction_gid",
            "target_payee_gid",
            "owner_uri",
            "source_event_id",
        ):
            _text(operation.get(field), f"{prefix}.{field}")
        if operation["transaction_entity"] not in _ENTITIES:
            raise PlanValidationError(
                f"{prefix}.transaction_entity is not enabled by P1F"
            )
        if (
            operation["owner_uri"] != plan["owner_uri"]
            or operation["source_event_id"] != plan["source_event_id"]
        ):
            raise PlanValidationError(
                f"{prefix} owner_uri and source_event_id must match the envelope"
            )
        transaction_gid = operation["transaction_gid"]
        if transaction_gid in transaction_gids:
            raise PlanValidationError("operations must not target a transaction twice")
        transaction_gids.add(transaction_gid)
        old = operation.get("expected_old_payee_gid")
        if old is not None:
            _text(old, f"{prefix}.expected_old_payee_gid")
        postcondition = operation.get("expected_postcondition")
        if (
            not isinstance(postcondition, Mapping)
            or set(postcondition) != {"payee_gid"}
            or postcondition.get("payee_gid") != operation.get("target_payee_gid")
        ):
            raise PlanValidationError(
                f"{prefix}.expected_postcondition.payee_gid must equal target_payee_gid"
            )
        if operation.get("allowed_changed_fields") != ["payee"]:
            raise PlanValidationError(
                f"{prefix}.allowed_changed_fields must be ['payee']"
            )
    actual = compute_digest(plan)
    supplied = plan.get("plan_digest")
    if supplied is not None and (
        not isinstance(supplied, str)
        or not _HEX_DIGEST.fullmatch(supplied)
        or supplied != actual
    ):
        raise PlanValidationError("plan_digest does not match canonical plan bytes")
    plan["plan_digest"] = actual
    return plan


def load_plan(path: str) -> dict[str, Any]:
    """Load and validate one UTF-8 JSON plan."""
    try:
        with open(path, encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanValidationError(f"cannot load plan: {exc}") from exc
    return validate_plan(payload)


def validate_result(plan: dict[str, Any], result: object) -> dict[str, Any]:
    """Validate durable per-operation receipts at every consumer boundary."""
    if not isinstance(result, dict) or result.get("contract_version") != 2:
        raise PlanValidationError("native result is not a version-2 receipt")
    if (
        result.get("plan_id") != plan["plan_id"]
        or result.get("plan_digest") != plan["plan_digest"]
    ):
        raise PlanValidationError("native result does not bind to the reviewed plan")
    classification = result.get("classification")
    if classification not in {"applied", "noop", "unknown", "retry_safe"}:
        raise PlanValidationError("native result has an invalid classification")
    success = classification in {"applied", "noop"}
    if result.get("verified") is not success:
        raise PlanValidationError(
            "native result verification contradicts its classification"
        )
    receipts = result.get("operations")
    if not isinstance(receipts, list) or len(receipts) != len(plan["operations"]):
        raise PlanValidationError("native result omits operation receipts")
    expected = {
        operation["operation_id"]: operation for operation in plan["operations"]
    }
    seen: set[str] = set()
    uris: set[str] = set()
    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise PlanValidationError("native operation receipt is malformed")
        operation_id = receipt.get("operation_id")
        if (
            not isinstance(operation_id, str)
            or operation_id not in expected
            or operation_id in seen
        ):
            raise PlanValidationError(
                "native result contains missing or duplicate operation identities"
            )
        seen.add(operation_id)
        operation = expected[operation_id]
        if any(
            receipt.get(field) != operation[field]
            for field in ("transaction_gid", "transaction_entity")
        ):
            raise PlanValidationError(
                "native operation receipt identifies another transaction"
            )
        status = classification if success else "unknown"
        if receipt.get("status") != status:
            raise PlanValidationError(
                "native operation status contradicts its unit classification"
            )
        numeric_id, uri = (
            receipt.get("durable_numeric_id"),
            receipt.get("durable_uri"),
        )
        if (
            not isinstance(numeric_id, str)
            or not numeric_id.isascii()
            or not numeric_id.isdigit()
            or int(numeric_id) <= 0
        ):
            raise PlanValidationError(
                "native operation receipt has no durable numeric identity"
            )
        if (
            not isinstance(uri, str)
            or not uri.startswith(
                f"x-coredata://{plan['store_identity']['store_uuid']}/"
            )
            or not uri.endswith(f"/p{numeric_id}")
            or uri in uris
        ):
            raise PlanValidationError(
                "native operation receipt has no matching durable store identity"
            )
        uris.add(uri)
        if success and receipt.get("new_payee_gid") != operation["target_payee_gid"]:
            raise PlanValidationError(
                "native operation receipt violates its postcondition"
            )
    return result
