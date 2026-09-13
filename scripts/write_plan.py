"""Strict, versioned plans for the P1F Core Data writer bridge."""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, NotRequired, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CONTRACT_VERSION = 2
OPERATION_SCHEMA_VERSION = 1
PAYEE_CAPABILITY = "write.reassign-payees-by-id"
CREATE_OPERATION_POLICIES = {
    "create_income": ("write.create-income", "DepositTransaction", 1),
    "create_expense": ("write.create-expense", "WithdrawTransaction", -1),
    "create_refund": ("write.create-refund", "RefundTransaction", 1),
}
CREATE_CAPABILITIES = frozenset(
    capability for capability, _entity, _sign in CREATE_OPERATION_POLICIES.values()
)
_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_WHOLE_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$"
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
    """The preserved P1F payee operation schema."""

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


class CategorySplit(TypedDict):
    """One exact category assignment for a created transaction."""

    category_gid: str
    amount: str


class RefundReference(TypedDict):
    """The original supported withdrawal referenced by a refund."""

    original_transaction_entity: str
    original_transaction_gid: str


class CreateTransactionOperation(TypedDict):
    """One strict W01 ordinary transaction creation operation."""

    operation_id: str
    kind: str
    capability: str
    transaction_entity: str
    transaction_gid: str
    account_gid: str
    owner_uri: str
    source_event_id: str
    amount: str
    currency_unit: str
    occurred_at: str
    timezone: str
    payee_gid: str | None
    category_splits: list[CategorySplit]
    tag_gids: list[str]
    note: str | None
    refund_reference: RefundReference | None
    expected_balance_delta: str
    expected_postcondition: dict[str, Any]


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
    operations: list[PayeeReassignmentOperation | CreateTransactionOperation]


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


def normalize_decimal(value: object, field: str) -> str:
    """Return one non-exponent decimal representation for a validated value."""
    parsed = Decimal(_decimal(value, field))
    if parsed == 0:
        return "0"
    return format(parsed.normalize(), "f")


def _canonical_decimal(value: object, field: str) -> str:
    original = _decimal(value, field)
    canonical = normalize_decimal(original, field)
    if original != canonical:
        raise PlanValidationError(f"{field} must use canonical decimal text")
    return canonical


def _whole_timestamp(value: object, field: str) -> str:
    timestamp = _timestamp(value, field)
    if not _WHOLE_TIMESTAMP.fullmatch(timestamp):
        raise PlanValidationError(f"{field} must use whole-second precision")
    return timestamp


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise PlanValidationError(f"{field} must be a nonempty list")
    return [_text(item, f"{field}[]") for item in value]


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _currency(value: object, field: str) -> str:
    value = _text(value, field)
    if not _CURRENCY.fullmatch(value):
        raise PlanValidationError(f"{field} must be a canonical three-letter currency")
    return value


def deterministic_transaction_gid(
    *, store_uuid: str, owner_uri: str, source_event_id: str
) -> str:
    """Derive one stable UUID-shaped GID from the source identity boundary."""
    identity = {
        "owner_uri": owner_uri,
        "source_event_id": source_event_id,
        "store_uuid": store_uuid,
    }
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest[:16])).upper()


def _validate_timezone_offset(timestamp: str, timezone: str, field: str) -> None:
    parsed = datetime.fromisoformat(timestamp)
    expected = parsed.astimezone(ZoneInfo(timezone)).utcoffset()
    if parsed.utcoffset() != expected:
        raise PlanValidationError(f"{field} offset does not match timezone")


def _validate_payee_operation(
    operation: Mapping[str, Any], prefix: str, plan: dict[str, Any]
) -> str:
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
    if operation.get("kind") != "reassign_payee":
        raise PlanValidationError(f"{prefix}.kind is not enabled")
    if operation.get("capability") != PAYEE_CAPABILITY:
        raise PlanValidationError(f"{prefix}.capability is not enabled")
    for field in (
        "transaction_entity",
        "transaction_gid",
        "target_payee_gid",
        "owner_uri",
        "source_event_id",
    ):
        _text(operation.get(field), f"{prefix}.{field}")
    if operation["transaction_entity"] not in _ENTITIES:
        raise PlanValidationError(f"{prefix}.transaction_entity is not enabled")
    if (
        operation["owner_uri"] != plan["owner_uri"]
        or operation["source_event_id"] != plan["source_event_id"]
    ):
        raise PlanValidationError(
            f"{prefix} owner_uri and source_event_id must match the envelope"
        )
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
        raise PlanValidationError(f"{prefix}.allowed_changed_fields must be ['payee']")
    return operation["transaction_gid"]


def _validate_category_splits(
    value: object, *, prefix: str, transaction_amount: Decimal
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise PlanValidationError(f"{prefix} must be a list")
    validated: list[dict[str, str]] = []
    seen: set[str] = set()
    total = Decimal(0)
    for index, split in enumerate(value):
        split_prefix = f"{prefix}[{index}]"
        if not isinstance(split, Mapping) or set(split) != {"category_gid", "amount"}:
            raise PlanValidationError(f"{split_prefix} has unknown or missing fields")
        category_gid = _text(split.get("category_gid"), f"{split_prefix}.category_gid")
        if category_gid in seen:
            raise PlanValidationError("category_splits must not repeat a category")
        seen.add(category_gid)
        amount = _canonical_decimal(split.get("amount"), f"{split_prefix}.amount")
        parsed = Decimal(amount)
        if parsed == 0 or (parsed > 0) != (transaction_amount > 0):
            raise PlanValidationError(
                "category split signs must match transaction amount"
            )
        total += parsed
        validated.append({"category_gid": category_gid, "amount": amount})
    if validated and total != transaction_amount:
        raise PlanValidationError(
            "category split amounts must sum to transaction amount"
        )
    if validated != sorted(validated, key=lambda item: item["category_gid"]):
        raise PlanValidationError("category_splits must be sorted by category_gid")
    return validated


def _validate_refund_reference(
    value: object, *, prefix: str, refund: bool
) -> dict[str, str] | None:
    if not refund:
        if value is not None:
            raise PlanValidationError(f"{prefix} is only valid for refunds")
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "original_transaction_entity",
        "original_transaction_gid",
    }:
        raise PlanValidationError(f"{prefix} must identify one original withdrawal")
    if value.get("original_transaction_entity") != "WithdrawTransaction":
        raise PlanValidationError(f"{prefix} must reference WithdrawTransaction")
    return {
        "original_transaction_entity": "WithdrawTransaction",
        "original_transaction_gid": _text(
            value.get("original_transaction_gid"),
            f"{prefix}.original_transaction_gid",
        ),
    }


def _create_postcondition(operation: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
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
    return {field: deepcopy(operation[field]) for field in fields}


def _validate_create_operation(
    operation: Mapping[str, Any], prefix: str, plan: dict[str, Any]
) -> str:
    expected_keys = {
        "operation_id",
        "kind",
        "capability",
        "transaction_entity",
        "transaction_gid",
        "account_gid",
        "owner_uri",
        "source_event_id",
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
        "expected_postcondition",
    }
    if set(operation) != expected_keys:
        raise PlanValidationError(f"{prefix} has unknown or missing fields")
    kind = operation.get("kind")
    if kind not in CREATE_OPERATION_POLICIES:
        raise PlanValidationError(f"{prefix}.kind is not enabled")
    capability, entity, sign = CREATE_OPERATION_POLICIES[kind]
    if operation.get("capability") != capability or plan["capability"] != capability:
        raise PlanValidationError(f"{prefix}.capability does not match its kind")
    if operation.get("transaction_entity") != entity:
        raise PlanValidationError(
            f"{prefix}.transaction_entity does not match its kind"
        )
    for field in ("transaction_gid", "account_gid", "owner_uri", "source_event_id"):
        _text(operation.get(field), f"{prefix}.{field}")
    if (
        operation["owner_uri"] != plan["owner_uri"]
        or operation["source_event_id"] != plan["source_event_id"]
        or operation["account_gid"] != plan["expected_account_gid"]
    ):
        raise PlanValidationError(
            f"{prefix} owner, source event, and account must match the envelope"
        )
    expected_gid = deterministic_transaction_gid(
        store_uuid=plan["store_identity"]["store_uuid"],
        owner_uri=plan["owner_uri"],
        source_event_id=plan["source_event_id"],
    )
    if operation["transaction_gid"] != expected_gid:
        raise PlanValidationError(f"{prefix}.transaction_gid is not deterministic")
    amount = _canonical_decimal(operation.get("amount"), f"{prefix}.amount")
    parsed_amount = Decimal(amount)
    if parsed_amount == 0 or (parsed_amount > 0) != (sign > 0):
        raise PlanValidationError(f"{prefix}.amount has the wrong sign for {kind}")
    currency = _currency(operation.get("currency_unit"), f"{prefix}.currency_unit")
    occurred_at = _whole_timestamp(
        operation.get("occurred_at"), f"{prefix}.occurred_at"
    )
    timezone = _text(operation.get("timezone"), f"{prefix}.timezone")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise PlanValidationError(
            f"{prefix}.timezone must be an IANA timezone"
        ) from exc
    _validate_timezone_offset(occurred_at, timezone, f"{prefix}.occurred_at")
    if currency != plan["currency_unit"] or timezone != plan["timezone"]:
        raise PlanValidationError(
            f"{prefix} currency_unit and timezone must match the envelope"
        )
    _optional_text(operation.get("payee_gid"), f"{prefix}.payee_gid")
    _validate_category_splits(
        operation.get("category_splits"),
        prefix=f"{prefix}.category_splits",
        transaction_amount=parsed_amount,
    )
    tags = operation.get("tag_gids")
    if not isinstance(tags, list):
        raise PlanValidationError(f"{prefix}.tag_gids must be a list")
    validated_tags = [_text(tag, f"{prefix}.tag_gids[]") for tag in tags]
    if len(set(validated_tags)) != len(validated_tags) or validated_tags != sorted(
        validated_tags
    ):
        raise PlanValidationError(f"{prefix}.tag_gids must be unique and sorted")
    _optional_text(operation.get("note"), f"{prefix}.note")
    _validate_refund_reference(
        operation.get("refund_reference"),
        prefix=f"{prefix}.refund_reference",
        refund=kind == "create_refund",
    )
    balance_delta = _canonical_decimal(
        operation.get("expected_balance_delta"),
        f"{prefix}.expected_balance_delta",
    )
    if Decimal(balance_delta) != parsed_amount:
        raise PlanValidationError(f"{prefix}.expected_balance_delta must equal amount")
    postcondition = operation.get("expected_postcondition")
    if not isinstance(postcondition, Mapping) or dict(
        postcondition
    ) != _create_postcondition(operation):
        raise PlanValidationError(
            f"{prefix}.expected_postcondition must exactly match all requested fields"
        )
    return operation["transaction_gid"]


def validate_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the complete v2 envelope and its strict operation union."""
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
    capability = plan.get("capability")
    if capability not in {PAYEE_CAPABILITY, *CREATE_CAPABILITIES}:
        raise PlanValidationError("capability is not enabled")
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
    create_operations = 0
    for index, operation in enumerate(operations):
        prefix = f"operations[{index}]"
        if not isinstance(operation, Mapping):
            raise PlanValidationError(f"{prefix} must be an object")
        operation_id = _text(operation.get("operation_id"), f"{prefix}.operation_id")
        if operation_id in operation_ids:
            raise PlanValidationError("operation_id values must be unique")
        operation_ids.add(operation_id)
        kind = operation.get("kind")
        if kind == "reassign_payee":
            if plan["capability"] != PAYEE_CAPABILITY:
                raise PlanValidationError(
                    f"{prefix}.kind does not match the envelope capability"
                )
            transaction_gid = _validate_payee_operation(operation, prefix, plan)
        elif kind in CREATE_OPERATION_POLICIES:
            create_operations += 1
            transaction_gid = _validate_create_operation(operation, prefix, plan)
        else:
            raise PlanValidationError(f"{prefix}.kind is not enabled")
        if transaction_gid in transaction_gids:
            raise PlanValidationError("operations must not target a transaction twice")
        transaction_gids.add(transaction_gid)
    if create_operations and len(operations) != 1:
        raise PlanValidationError(
            "a W01 source event must create exactly one transaction"
        )
    if create_operations:
        _whole_timestamp(plan["created_at"], "created_at")
    if not create_operations and plan["capability"] != PAYEE_CAPABILITY:
        raise PlanValidationError("create capability requires a create operation")
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
        creation_retry_safe = (
            operation["kind"] in CREATE_OPERATION_POLICIES
            and classification == "retry_safe"
        )
        if creation_retry_safe:
            if numeric_id is not None or uri is not None:
                raise PlanValidationError(
                    "retry-safe creation receipt must not claim a durable identity"
                )
        elif (
            not isinstance(numeric_id, str)
            or not numeric_id.isascii()
            or not numeric_id.isdigit()
            or int(numeric_id) <= 0
        ):
            raise PlanValidationError(
                "native operation receipt has no durable numeric identity"
            )
        if not creation_retry_safe:
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
        if operation["kind"] == "reassign_payee":
            if (
                success
                and receipt.get("new_payee_gid") != operation["target_payee_gid"]
            ):
                raise PlanValidationError(
                    "native operation receipt violates its payee postcondition"
                )
        elif success:
            if receipt.get("postcondition") != operation["expected_postcondition"]:
                raise PlanValidationError(
                    "native operation receipt violates its creation postcondition"
                )
        elif receipt.get("postcondition") is not None:
            raise PlanValidationError(
                "unverified creation receipt must not claim a postcondition"
            )
    return result
