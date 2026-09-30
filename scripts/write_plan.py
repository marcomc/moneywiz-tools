"""Strict, versioned plans for the P1F Core Data writer bridge."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
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
EDIT_CAPABILITY = "write.edit-transaction"
ASSIGN_CAPABILITY = "write.assign-payee-categories"
RECONCILE_CAPABILITIES = {
    "reconcile_transaction": ("write.reconcile", False, True),
    "unreconcile_transaction": ("write.unreconcile", True, False),
}
ADJUST_BALANCE_CAPABILITY = "write.adjust-balance-investment-total"
DELETE_ADJUSTMENT_CAPABILITY = "write.delete-adjust-balance-investment-total"
TRANSFER_CAPABILITY = "write.replace-import-with-transfer"
INVESTMENT_POLICIES = {
    "investment_income": ("write.investment-income", "DepositTransaction", 1),
    "investment_expense": ("write.investment-expense", "WithdrawTransaction", -1),
    "investment_buy": ("write.investment-buy", "InvestmentBuyTransaction", -1),
    "investment_sell": ("write.investment-sell", "InvestmentSellTransaction", 1),
}
INVESTMENT_CAPABILITIES = frozenset(item[0] for item in INVESTMENT_POLICIES.values())
PAYEE_MERGE_CAPABILITIES = {
    "merge_exact_payee": "write.merge-exact-payees",
    "merge_approved_fuzzy_payee": "write.merge-approved-fuzzy-payees",
}
EDIT_ENTITIES = frozenset(
    {"DepositTransaction", "WithdrawTransaction", "RefundTransaction"}
)
EDIT_FIELDS = {
    "amount": ("amount", "originalAmount"),
    "occurred_at": ("date",),
    "note": ("notes",),
    "description": ("desc",),
    "checkbook_number": ("checkbookNumber",),
}
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


class EditTransactionOperation(TypedDict):
    """One identity-preserving W02 scalar edit with complete prior-value guards."""

    operation_id: str
    kind: str
    capability: str
    transaction_entity: str
    transaction_gid: str
    account_gid: str
    owner_uri: str
    source_event_id: str
    currency_unit: str
    timezone: str
    changes: dict[str, str | None]
    expected_prior: dict[str, str | None]
    expected_balance_delta: str
    expected_postcondition: dict[str, Any]
    allowed_changed_fields: list[str]
    correction_mode: str


class AssignTransactionOperation(TypedDict):
    """Replace the payee and category assignments of one exact transaction."""

    operation_id: str
    kind: str
    capability: str
    transaction_entity: str
    transaction_gid: str
    account_gid: str
    owner_uri: str
    source_event_id: str
    currency_unit: str
    amount: str
    expected_assignments: dict[str, Any]
    target: dict[str, Any]
    replacement_mode: str
    expected_balance_delta: str
    expected_postcondition: dict[str, Any]
    allowed_changed_fields: list[str]


class ReconcileTransactionOperation(TypedDict):
    """One guarded W04 native reconciliation-flag transition."""

    operation_id: str
    kind: str
    capability: str
    transaction_entity: str
    transaction_gid: str
    account_gid: str
    owner_uri: str
    source_event_id: str
    expected_reconciled: bool
    target_reconciled: bool
    expected_native_status: int
    expected_native_flags: int
    correction_reason: str | None
    expected_balance_delta: str
    expected_postcondition: dict[str, Any]
    allowed_changed_fields: list[str]


class AdjustBalanceOperation(TypedDict):
    """One W05 aggregate investment balance adjustment."""

    operation_id: str
    kind: str
    capability: str
    transaction_entity: str
    transaction_gid: str
    account_gid: str
    owner_uri: str
    source_event_id: str
    balance_unit: str
    expected_prior_balance: str
    target_balance: str
    expected_balance_delta: str
    currency_unit: str
    occurred_at: str
    timezone: str
    expected_postcondition: dict[str, str]


class DeleteAdjustmentOperation(TypedDict):
    """Delete one exact, latest aggregate investment adjustment."""

    operation_id: str
    kind: str
    capability: str
    transaction_entity: str
    transaction_gid: str
    transaction_numeric_id: str
    account_gid: str
    owner_uri: str
    source_event_id: str
    balance_unit: str
    expected_amount: str
    expected_reconcile_amount: str
    expected_prior_balance: str
    target_balance: str
    expected_balance_delta: str
    currency_unit: str
    occurred_at: str
    timezone: str
    deletion_reason: str
    expected_postcondition: dict[str, Any]


class TransferReplacementOperation(TypedDict):
    """Replace one or two imported rows with a reciprocal zero-fee transfer."""

    operation_id: str
    kind: str
    capability: str
    transaction_entity: str
    transaction_gid: str
    recipient_transaction_gid: str
    owner_uri: str
    source_event_id: str
    source_old: dict[str, Any]
    destination_old: dict[str, Any] | None
    send_at: str
    receive_at: str
    sender_amount: str
    recipient_amount: str
    exchange_rate: str
    fee_amount: str
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
    source_scope: NotRequired[dict[str, Any]]
    destination_account: NotRequired[dict[str, str]]
    operations: list[
        PayeeReassignmentOperation
        | CreateTransactionOperation
        | EditTransactionOperation
        | AssignTransactionOperation
        | ReconcileTransactionOperation
        | AdjustBalanceOperation
        | DeleteAdjustmentOperation
        | TransferReplacementOperation
        | dict[str, Any]
    ]


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


def edit_changed_fields(changes: Mapping[str, Any]) -> list[str]:
    """Map the closed logical allowlist to its exact native mutation surface."""
    if not changes or not set(changes) <= EDIT_FIELDS.keys():
        raise PlanValidationError("changes must contain only supported W02 fields")
    return sorted({native for field in changes for native in EDIT_FIELDS[field]})


def _validate_edit_operation(
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
        "currency_unit",
        "timezone",
        "changes",
        "expected_prior",
        "expected_balance_delta",
        "expected_postcondition",
        "allowed_changed_fields",
        "correction_mode",
    }
    if set(operation) != expected_keys:
        raise PlanValidationError(f"{prefix} has unknown or missing fields")
    if (
        operation.get("capability") != EDIT_CAPABILITY
        or plan["capability"] != EDIT_CAPABILITY
    ):
        raise PlanValidationError(f"{prefix}.capability does not match its kind")
    if operation.get("transaction_entity") not in EDIT_ENTITIES:
        raise PlanValidationError(f"{prefix}.transaction_entity is not enabled for W02")
    for field in ("transaction_gid", "account_gid", "owner_uri", "source_event_id"):
        _text(operation.get(field), f"{prefix}.{field}")
    for field, envelope in (
        ("account_gid", "expected_account_gid"),
        ("owner_uri", "owner_uri"),
        ("source_event_id", "source_event_id"),
        ("currency_unit", "currency_unit"),
        ("timezone", "timezone"),
    ):
        if operation[field] != plan[envelope]:
            raise PlanValidationError(f"{prefix}.{field} must match the envelope")
    _currency(operation["currency_unit"], f"{prefix}.currency_unit")
    if operation["correction_mode"] != "reject_reconciled":
        raise PlanValidationError("reconciled correction semantics are not enabled")
    changes, prior = operation["changes"], operation["expected_prior"]
    if not isinstance(changes, Mapping) or not isinstance(prior, Mapping):
        raise PlanValidationError("changes and expected_prior must be objects")
    allowed = edit_changed_fields(changes)
    if set(changes) != set(prior):
        raise PlanValidationError(
            "expected_prior must cover exactly every changed field"
        )
    if operation["allowed_changed_fields"] != allowed:
        raise PlanValidationError(
            "allowed_changed_fields must match the native W02 allowlist"
        )
    delta = Decimal(0)
    for field, value in changes.items():
        previous = prior[field]
        if field == "amount":
            old_amount = Decimal(_canonical_decimal(previous, "expected_prior.amount"))
            amount = Decimal(_canonical_decimal(value, "changes.amount"))
            positive = operation["transaction_entity"] != "WithdrawTransaction"
            if any(
                number == 0 or (number > 0) != positive
                for number in (old_amount, amount)
            ):
                raise PlanValidationError(
                    "amount has the wrong sign for the transaction entity"
                )
            delta = amount - old_amount
        elif field == "occurred_at":
            for timestamp in (previous, value):
                _whole_timestamp(timestamp, field)
                _validate_timezone_offset(timestamp, operation["timezone"], field)
            if datetime.fromisoformat(previous) == datetime.fromisoformat(value):
                raise PlanValidationError(
                    "W02 changes must not contain unchanged values"
                )
        else:
            _optional_text(previous, f"expected_prior.{field}")
            _optional_text(value, f"changes.{field}")
        if previous == value:
            raise PlanValidationError("W02 changes must not contain unchanged values")
    expected_delta = _canonical_decimal(
        operation["expected_balance_delta"], "expected_balance_delta"
    )
    if Decimal(expected_delta) != delta:
        raise PlanValidationError(
            "expected_balance_delta must equal the amount difference"
        )
    if operation["expected_postcondition"] != {
        "fields": dict(changes),
        "expected_balance_delta": expected_delta,
    }:
        raise PlanValidationError(
            "expected_postcondition must exactly match requested W02 fields"
        )
    return operation["transaction_gid"]


def _validate_assign_operation(
    operation: Mapping[str, Any], prefix: str, plan: dict[str, Any]
) -> str:
    required = {
        "operation_id", "kind", "capability", "transaction_entity",
        "transaction_gid", "account_gid", "owner_uri", "source_event_id",
        "currency_unit", "amount", "expected_assignments", "target",
        "replacement_mode", "expected_balance_delta", "expected_postcondition",
        "allowed_changed_fields",
    }
    if set(operation) != required:
        raise PlanValidationError(f"{prefix} has unknown or missing fields")
    if operation["capability"] != ASSIGN_CAPABILITY or plan["capability"] != ASSIGN_CAPABILITY:
        raise PlanValidationError(f"{prefix}.capability does not match W03")
    if operation["transaction_entity"] not in EDIT_ENTITIES:
        raise PlanValidationError(f"{prefix}.transaction_entity is not enabled for W03")
    for field in ("transaction_gid", "account_gid", "owner_uri", "source_event_id"):
        _text(operation[field], f"{prefix}.{field}")
    for field, envelope in (("account_gid", "expected_account_gid"),
                            ("owner_uri", "owner_uri"),
                            ("source_event_id", "source_event_id"),
                            ("currency_unit", "currency_unit")):
        if operation[field] != plan[envelope]:
            raise PlanValidationError(f"{prefix}.{field} must match the envelope")
    if operation["replacement_mode"] != "replace":
        raise PlanValidationError("W03 requires deliberate relationship replacement")
    amount = Decimal(_canonical_decimal(operation["amount"], f"{prefix}.amount"))
    positive = operation["transaction_entity"] != "WithdrawTransaction"
    if amount == 0 or (amount > 0) != positive:
        raise PlanValidationError("W03 amount has the wrong sign")
    states = []
    for name in ("expected_assignments", "target"):
        state = operation[name]
        if not isinstance(state, Mapping) or set(state) != {"payee_gid", "category_splits"}:
            raise PlanValidationError(f"{prefix}.{name} has unknown or missing fields")
        _optional_text(state["payee_gid"], f"{prefix}.{name}.payee_gid")
        _validate_category_splits(state["category_splits"],
                                  prefix=f"{prefix}.{name}.category_splits",
                                  transaction_amount=amount)
        states.append(dict(state))
    if states[0] == states[1]:
        raise PlanValidationError("W03 target must differ from expected_assignments")
    if operation["allowed_changed_fields"] != ["payee", "categoriesAssigments"]:
        raise PlanValidationError("W03 native relationship allowlist differs")
    if operation["expected_balance_delta"] != "0":
        raise PlanValidationError("W03 must preserve the account balance")
    if operation["expected_postcondition"] != {**states[1], "expected_balance_delta": "0"}:
        raise PlanValidationError("W03 postcondition must match target relationships")
    return operation["transaction_gid"]


def _validate_reconcile_operation(
    operation: Mapping[str, Any], prefix: str, plan: dict[str, Any]
) -> str:
    required = {
        "operation_id", "kind", "capability", "transaction_entity",
        "transaction_gid", "account_gid", "owner_uri", "source_event_id",
        "expected_reconciled", "target_reconciled", "expected_native_status",
        "expected_native_flags", "correction_reason", "expected_balance_delta",
        "expected_postcondition", "allowed_changed_fields",
    }
    if set(operation) != required:
        raise PlanValidationError(f"{prefix} has unknown or missing fields")
    capability, old, target = RECONCILE_CAPABILITIES[operation["kind"]]
    if operation["capability"] != capability or plan["capability"] != capability:
        raise PlanValidationError(f"{prefix}.capability does not match W04 kind")
    if operation["transaction_entity"] not in EDIT_ENTITIES:
        raise PlanValidationError("W04 supports only ordinary income, expense and refund")
    for field in ("transaction_gid", "account_gid", "owner_uri", "source_event_id"):
        _text(operation[field], f"{prefix}.{field}")
    for field, envelope in (("account_gid", "expected_account_gid"),
                            ("owner_uri", "owner_uri"),
                            ("source_event_id", "source_event_id")):
        if operation[field] != plan[envelope]:
            raise PlanValidationError(f"{prefix}.{field} must match the envelope")
    if (type(operation["expected_reconciled"]) is not bool
            or type(operation["target_reconciled"]) is not bool
            or operation["expected_reconciled"] is not old
            or operation["target_reconciled"] is not target):
        raise PlanValidationError("W04 reconciliation state does not match capability")
    for field in ("expected_native_status", "expected_native_flags"):
        value = operation[field]
        if type(value) is not int or value < 0 or value > 32767:
            raise PlanValidationError(f"{prefix}.{field} must be a native nonnegative integer")
    if operation["expected_native_status"] != 1:
        raise PlanValidationError("W04 requires an active native transaction status")
    reason = operation["correction_reason"]
    if operation["kind"] == "unreconcile_transaction":
        _text(reason, f"{prefix}.correction_reason")
    elif reason is not None:
        raise PlanValidationError("reconcile does not accept a correction reason")
    if operation["expected_balance_delta"] != "0":
        raise PlanValidationError("W04 must preserve account balance")
    if operation["allowed_changed_fields"] != ["reconciled"]:
        raise PlanValidationError("W04 native field allowlist differs")
    postcondition = {
        "reconciled": target,
        "native_status": operation["expected_native_status"],
        "native_flags": operation["expected_native_flags"],
        "expected_balance_delta": "0",
    }
    if operation["expected_postcondition"] != postcondition:
        raise PlanValidationError("W04 postcondition differs from requested flags")
    return operation["transaction_gid"]


def _validate_adjust_balance_operation(
    operation: Mapping[str, Any], prefix: str, plan: dict[str, Any]
) -> str:
    fields = {
        "transaction_entity", "transaction_gid", "account_gid", "owner_uri",
        "balance_unit", "expected_prior_balance", "target_balance",
        "expected_balance_delta", "currency_unit", "occurred_at", "timezone",
    }
    required = fields | {
        "operation_id", "kind", "capability", "source_event_id",
        "expected_postcondition",
    }
    if set(operation) != required:
        raise PlanValidationError(f"{prefix} has unknown or missing W05 fields")
    if (operation.get("kind") != "adjust_investment_total"
            or operation.get("capability") != ADJUST_BALANCE_CAPABILITY
            or plan["capability"] != ADJUST_BALANCE_CAPABILITY
            or operation.get("transaction_entity") != "ReconcileTransaction"
            or operation.get("balance_unit") != "investment_total"):
        raise PlanValidationError(f"{prefix} is not the observed W05 variant")
    for field, envelope in (
        ("account_gid", "expected_account_gid"),
        ("owner_uri", "owner_uri"),
        ("source_event_id", "source_event_id"),
        ("currency_unit", "currency_unit"),
        ("timezone", "timezone"),
    ):
        if operation.get(field) != plan[envelope]:
            raise PlanValidationError(f"{prefix}.{field} must match the envelope")
    if operation.get("transaction_gid") != deterministic_transaction_gid(
        store_uuid=plan["store_identity"]["store_uuid"],
        owner_uri=plan["owner_uri"],
        source_event_id=plan["source_event_id"],
    ):
        raise PlanValidationError(f"{prefix}.transaction_gid is not deterministic")
    prior = _canonical_decimal(operation.get("expected_prior_balance"), f"{prefix}.expected_prior_balance")
    target = _canonical_decimal(operation.get("target_balance"), f"{prefix}.target_balance")
    delta = _canonical_decimal(operation.get("expected_balance_delta"), f"{prefix}.expected_balance_delta")
    if Decimal(target) - Decimal(prior) != Decimal(delta):
        raise PlanValidationError(f"{prefix}.expected_balance_delta differs from target minus prior")
    if plan["currency_unit"] != "GBP" or any(
        Decimal(value).as_tuple().exponent < -2 for value in (prior, target, delta)
    ):
        raise PlanValidationError("W05 is limited to GBP pence in the observed account shape")
    occurred_at = _whole_timestamp(operation.get("occurred_at"), f"{prefix}.occurred_at")
    _validate_timezone_offset(occurred_at, plan["timezone"], f"{prefix}.occurred_at")
    if plan["expected_cached_account_balance"] != "0":
        raise PlanValidationError("W05 requires the observed zero investment cash cache")
    if operation["account_gid"] != plan["expected_account_gid"]:
        raise PlanValidationError(f"{prefix}.account_gid must match the envelope")
    postcondition = operation.get("expected_postcondition")
    expected = {field: operation[field] for field in fields}
    if not isinstance(postcondition, Mapping) or dict(postcondition) != expected:
        raise PlanValidationError(f"{prefix}.expected_postcondition differs from reviewed fields")
    return operation["transaction_gid"]


def _validate_delete_adjustment_operation(
    operation: Mapping[str, Any], prefix: str, plan: dict[str, Any]
) -> str:
    required = {
        "operation_id", "kind", "capability", "transaction_entity",
        "transaction_gid", "transaction_numeric_id", "account_gid", "owner_uri",
        "source_event_id", "balance_unit", "expected_amount",
        "expected_reconcile_amount", "expected_prior_balance", "target_balance",
        "expected_balance_delta", "currency_unit", "occurred_at", "timezone",
        "deletion_reason", "expected_postcondition",
    }
    if set(operation) != required:
        raise PlanValidationError(f"{prefix} has unknown or missing W06 fields")
    if (
        operation["kind"] != "delete_investment_total_adjustment"
        or operation["capability"] != DELETE_ADJUSTMENT_CAPABILITY
        or plan["capability"] != DELETE_ADJUSTMENT_CAPABILITY
        or operation["transaction_entity"] != "ReconcileTransaction"
        or operation["balance_unit"] != "investment_total"
    ):
        raise PlanValidationError(f"{prefix} is not the observed W06 variant")
    for field, envelope in (
        ("account_gid", "expected_account_gid"), ("owner_uri", "owner_uri"),
        ("source_event_id", "source_event_id"), ("currency_unit", "currency_unit"),
        ("timezone", "timezone"),
    ):
        if operation[field] != plan[envelope]:
            raise PlanValidationError(f"{prefix}.{field} must match the envelope")
    _text(operation["transaction_gid"], f"{prefix}.transaction_gid")
    numeric_id = operation["transaction_numeric_id"]
    if (not isinstance(numeric_id, str) or not numeric_id.isascii()
            or not numeric_id.isdigit() or int(numeric_id) <= 0
            or str(int(numeric_id)) != numeric_id):
        raise PlanValidationError(f"{prefix}.transaction_numeric_id must be positive")
    _text(operation["deletion_reason"], f"{prefix}.deletion_reason")
    values = {
        name: _canonical_decimal(operation[name], f"{prefix}.{name}")
        for name in ("expected_amount", "expected_reconcile_amount",
                     "expected_prior_balance", "target_balance", "expected_balance_delta")
    }
    if (Decimal(values["expected_amount"]) == 0
            or Decimal(values["expected_reconcile_amount"]) != Decimal(values["expected_prior_balance"])
            or Decimal(values["target_balance"]) !=
            Decimal(values["expected_prior_balance"]) - Decimal(values["expected_amount"])
            or Decimal(values["expected_balance_delta"]) != -Decimal(values["expected_amount"])):
        raise PlanValidationError("W06 target, prior balance and deletion delta disagree")
    if plan["currency_unit"] != "GBP" or any(
        Decimal(value).as_tuple().exponent < -2 for value in values.values()
    ) or plan["expected_cached_account_balance"] != "0":
        raise PlanValidationError("W06 is limited to observed GBP investment totals")
    occurred_at = _timestamp(operation["occurred_at"], f"{prefix}.occurred_at")
    _validate_timezone_offset(occurred_at, plan["timezone"], f"{prefix}.occurred_at")
    expected_postcondition = {
        "transaction_absent": True,
        "transaction_gid": operation["transaction_gid"],
        "account_gid": operation["account_gid"],
        "target_balance": operation["target_balance"],
    }
    if operation["expected_postcondition"] != expected_postcondition:
        raise PlanValidationError("W06 postcondition differs from the reviewed deletion")
    return operation["transaction_gid"]


def _transfer_old_row(value: object, field: str, *, account_gid: str,
                      currency_unit: str, entity: str) -> dict[str, Any]:
    required = {
        "transaction_entity", "transaction_gid", "transaction_numeric_id",
        "account_gid", "amount", "currency_unit", "occurred_at", "status",
        "flags", "reconciled", "note", "description", "payee_gid",
        "tag_gids", "category_assignment_uris",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise PlanValidationError(f"{field} has unknown or missing fields")
    row = dict(value)
    if row["transaction_entity"] != entity or row["account_gid"] != account_gid:
        raise PlanValidationError(f"{field} entity or account differs from the plan")
    _text(row["transaction_gid"], f"{field}.transaction_gid")
    numeric_id = row["transaction_numeric_id"]
    if (not isinstance(numeric_id, str) or not numeric_id.isascii()
            or not numeric_id.isdigit() or int(numeric_id) <= 0
            or str(int(numeric_id)) != numeric_id):
        raise PlanValidationError(f"{field}.transaction_numeric_id must be positive")
    if row["currency_unit"] != currency_unit:
        raise PlanValidationError(f"{field}.currency_unit differs from the account")
    _canonical_decimal(row["amount"], f"{field}.amount")
    _timestamp(row["occurred_at"], f"{field}.occurred_at")
    if type(row["status"]) is not int or row["status"] != 2:
        raise PlanValidationError(f"{field}.status must be the observed cleared state")
    if type(row["flags"]) is not int or row["flags"] < 0:
        raise PlanValidationError(f"{field}.flags must be a nonnegative native integer")
    if type(row["reconciled"]) is not bool:
        raise PlanValidationError(f"{field}.reconciled must be boolean")
    for optional in ("note", "description", "payee_gid"):
        if row[optional] is not None and not isinstance(row[optional], str):
            raise PlanValidationError(f"{field}.{optional} must be text or null")
    for name in ("tag_gids", "category_assignment_uris"):
        items = row[name]
        if (not isinstance(items, list) or not all(isinstance(item, str)
                and item.strip() == item and item for item in items)
                or items != sorted(set(items))):
            raise PlanValidationError(f"{field}.{name} must be unique sorted strings")
    return row


def transfer_postcondition(plan: Mapping[str, Any], operation: Mapping[str, Any]) -> dict[str, Any]:
    """The stable part of W07 read-back; new numeric IDs belong in the receipt."""
    sender = operation["source_old"]
    receiver = operation["destination_old"]
    destination = plan["destination_account"]
    recipient_prior = Decimal(destination["expected_cached_balance"])
    recipient_final = recipient_prior if receiver else recipient_prior + Decimal(operation["recipient_amount"])
    return {
        "old_sender_gid": sender["transaction_gid"],
        "old_sender_numeric_id": sender["transaction_numeric_id"],
        "old_recipient_gid": receiver["transaction_gid"] if receiver else None,
        "old_recipient_numeric_id": receiver["transaction_numeric_id"] if receiver else None,
        "sender_gid": operation["transaction_gid"],
        "recipient_gid": operation["recipient_transaction_gid"],
        "sender_account_gid": plan["expected_account_gid"],
        "recipient_account_gid": destination["account_gid"],
        "sender_amount": operation["sender_amount"],
        "recipient_amount": operation["recipient_amount"],
        "send_at": operation["send_at"],
        "receive_at": operation["receive_at"],
        "exchange_rate": operation["exchange_rate"],
        "fee_amount": operation["fee_amount"],
        "sender_balance": normalize_decimal(plan["expected_cached_account_balance"], "sender_balance"),
        "recipient_balance": normalize_decimal(format(recipient_final, "f"), "recipient_balance"),
    }


def _validate_transfer_operation(
    operation: Mapping[str, Any], prefix: str, plan: dict[str, Any]
) -> str:
    required = {
        "operation_id", "kind", "capability", "transaction_entity",
        "transaction_gid", "recipient_transaction_gid", "owner_uri",
        "source_event_id", "source_old", "destination_old", "send_at",
        "receive_at", "sender_amount", "recipient_amount", "exchange_rate",
        "fee_amount", "expected_postcondition",
    }
    if set(operation) != required or operation["kind"] != "replace_import_with_transfer":
        raise PlanValidationError(f"{prefix} has unknown or missing W07 fields")
    if (operation["capability"] != TRANSFER_CAPABILITY
            or plan["capability"] != TRANSFER_CAPABILITY
            or operation["transaction_entity"] != "TransferWithdrawTransaction"
            or operation["owner_uri"] != plan["owner_uri"]
            or operation["source_event_id"] != plan["source_event_id"]):
        raise PlanValidationError("W07 operation differs from its envelope")
    destination = plan["destination_account"]
    sender = _transfer_old_row(
        operation["source_old"], f"{prefix}.source_old",
        account_gid=plan["expected_account_gid"],
        currency_unit=plan["currency_unit"], entity="WithdrawTransaction",
    )
    receiver = None
    if operation["destination_old"] is not None:
        receiver = _transfer_old_row(
            operation["destination_old"], f"{prefix}.destination_old",
            account_gid=destination["account_gid"],
            currency_unit=destination["currency_unit"], entity="DepositTransaction",
        )
        if (receiver["transaction_gid"] == sender["transaction_gid"]
                or receiver["transaction_numeric_id"] == sender["transaction_numeric_id"]):
            raise PlanValidationError("W07 old leg identities must be distinct")
    for name in ("send_at", "receive_at"):
        occurred = _timestamp(operation[name], f"{prefix}.{name}")
        _validate_timezone_offset(occurred, plan["timezone"], f"{prefix}.{name}")
    sender_amount = Decimal(_canonical_decimal(operation["sender_amount"], f"{prefix}.sender_amount"))
    recipient_amount = Decimal(_canonical_decimal(operation["recipient_amount"], f"{prefix}.recipient_amount"))
    rate = Decimal(_canonical_decimal(operation["exchange_rate"], f"{prefix}.exchange_rate"))
    fee = Decimal(_canonical_decimal(operation["fee_amount"], f"{prefix}.fee_amount"))
    if (sender_amount >= 0 or recipient_amount <= 0 or rate <= 0 or fee != 0
            or sender_amount != Decimal(sender["amount"])
            or (receiver is not None and recipient_amount != Decimal(receiver["amount"]))
            or abs(-sender_amount * rate - recipient_amount) > Decimal("0.01")):
        raise PlanValidationError("W07 amount, rate or zero-fee equation differs")
    expected_sender = deterministic_transaction_gid(
        store_uuid=plan["store_identity"]["store_uuid"], owner_uri=plan["owner_uri"],
        source_event_id=plan["source_event_id"] + ":withdraw",
    )
    expected_receiver = deterministic_transaction_gid(
        store_uuid=plan["store_identity"]["store_uuid"], owner_uri=plan["owner_uri"],
        source_event_id=plan["source_event_id"] + ":deposit",
    )
    if (operation["transaction_gid"] != expected_sender
            or operation["recipient_transaction_gid"] != expected_receiver):
        raise PlanValidationError("W07 new GIDs differ from the source event")
    if operation["expected_postcondition"] != transfer_postcondition(plan, operation):
        raise PlanValidationError("W07 postcondition differs from the reviewed pair")
    return operation["transaction_gid"]


def _validate_investment_operation(
    operation: Mapping[str, Any], prefix: str, plan: dict[str, Any]
) -> str:
    base = {
        "operation_id", "kind", "capability", "transaction_entity",
        "transaction_gid", "account_gid", "owner_uri", "source_event_id",
        "amount", "currency_unit", "occurred_at", "timezone", "payee_gid",
        "category_splits", "tag_gids", "note", "refund_reference",
        "expected_balance_delta", "expected_postcondition",
    }
    extra = {
        "account_mode", "cash_event_type", "investment_symbol", "holding_gid", "holding_symbol",
        "asset_type", "quantity", "unit_price", "fee", "fee_currency",
        "expected_prior_cash", "expected_final_cash", "expected_prior_units",
        "expected_final_units",
    }
    if set(operation) != base | extra:
        raise PlanValidationError(f"{prefix} has unknown or missing W08 fields")
    kind = operation.get("kind")
    if kind not in INVESTMENT_POLICIES:
        raise PlanValidationError(f"{prefix}.kind is not an investment operation")
    capability, entity, sign = INVESTMENT_POLICIES[kind]
    if (
        operation["capability"] != capability
        or plan["capability"] != capability
        or operation["transaction_entity"] != entity
        or operation["account_gid"] != plan["expected_account_gid"]
        or operation["owner_uri"] != plan["owner_uri"]
        or operation["source_event_id"] != plan["source_event_id"]
        or operation["currency_unit"] != plan["currency_unit"]
        or operation["timezone"] != plan["timezone"]
        or operation["transaction_gid"] != deterministic_transaction_gid(
            store_uuid=plan["store_identity"]["store_uuid"],
            owner_uri=plan["owner_uri"], source_event_id=plan["source_event_id"]
        )
    ):
        raise PlanValidationError("W08 operation identity differs from its envelope")
    if operation["account_mode"] not in {"aggregate", "units"}:
        raise PlanValidationError("W08 account_mode must be aggregate or units")
    if kind in {"investment_buy", "investment_sell"} and operation["account_mode"] != "units":
        raise PlanValidationError("W08 Buy/Sell requires a units-based account")
    for field in ("amount", "expected_balance_delta", "quantity", "unit_price", "fee",
                  "expected_prior_cash", "expected_final_cash"):
        _canonical_decimal(operation[field], f"{prefix}.{field}")
    amount = Decimal(operation["amount"])
    quantity = Decimal(operation["quantity"])
    price = Decimal(operation["unit_price"])
    fee = Decimal(operation["fee"])
    before_cash = Decimal(operation["expected_prior_cash"])
    after_cash = Decimal(operation["expected_final_cash"])
    if (
        amount == 0 or (amount > 0) != (sign > 0)
        or operation["expected_balance_delta"] != operation["amount"]
        or after_cash != before_cash + amount
        or fee < 0
        or any(Decimal(operation[field]).as_tuple().exponent < -2 for field in
               ("amount", "fee", "expected_prior_cash", "expected_final_cash"))
        or operation["fee_currency"] != plan["currency_unit"]
        or plan["expected_cached_account_balance"] != "0"
    ):
        raise PlanValidationError("W08 amount, fee or derived cash disagrees")
    _currency(operation["fee_currency"], f"{prefix}.fee_currency")
    _currency(plan["currency_unit"], "currency_unit")
    _whole_timestamp(operation["occurred_at"], f"{prefix}.occurred_at")
    _validate_timezone_offset(operation["occurred_at"], plan["timezone"], f"{prefix}.occurred_at")
    _optional_text(operation["payee_gid"], f"{prefix}.payee_gid")
    _optional_text(operation["note"], f"{prefix}.note")
    if operation["refund_reference"] is not None:
        raise PlanValidationError("W08 does not create refund links")
    if not isinstance(operation["tag_gids"], list) or operation["tag_gids"] != sorted(set(operation["tag_gids"])):
        raise PlanValidationError("W08 tags must be sorted and unique")
    for tag in operation["tag_gids"]:
        _text(tag, f"{prefix}.tag_gids[]")
    splits = _validate_category_splits(
        operation["category_splits"], prefix=f"{prefix}.category_splits",
        transaction_amount=amount,
    )
    if kind in {"investment_income", "investment_expense"}:
        allowed = ({"dividend", "interest", "sale_proceeds", "other_income"}
                   if sign > 0 else {"fee", "other_expense"})
        if operation["cash_event_type"] not in allowed or len(splits) != 1:
            raise PlanValidationError("W08 cash event requires its type and one category")
        if any(operation[field] is not None for field in
               ("holding_gid", "holding_symbol", "asset_type", "expected_prior_units", "expected_final_units")):
            raise PlanValidationError("W08 cash event must not fabricate a holding")
        _optional_text(operation["investment_symbol"], f"{prefix}.investment_symbol")
        if quantity != 0 or price != 0 or fee != 0:
            raise PlanValidationError("W08 cash event has no quantity, price or transaction fee")
    else:
        if operation["cash_event_type"] is not None or operation["investment_symbol"] is not None or splits:
            raise PlanValidationError("W08 Buy/Sell has no cash-event category")
        _text(operation["holding_gid"], f"{prefix}.holding_gid")
        _text(operation["holding_symbol"], f"{prefix}.holding_symbol")
        if type(operation["asset_type"]) is not int or operation["asset_type"] < 0:
            raise PlanValidationError("W08 asset_type must be a native nonnegative integer")
        for field in ("expected_prior_units", "expected_final_units"):
            _canonical_decimal(operation[field], f"{prefix}.{field}")
        prior_units = Decimal(operation["expected_prior_units"])
        final_units = Decimal(operation["expected_final_units"])
        if (
            quantity <= 0 or price <= 0 or prior_units < 0 or final_units < 0
            or final_units != prior_units + (quantity if sign < 0 else -quantity)
            or amount != (-(quantity * price + fee) if sign < 0 else quantity * price - fee)
        ):
            raise PlanValidationError("W08 quantity, price, fee and units disagree")
    if operation["expected_postcondition"] != _create_postcondition(operation):
        raise PlanValidationError("W08 postcondition differs from requested creation")
    return operation["transaction_gid"]


def _validate_source_scope(scope: object, plan: dict[str, Any]) -> list[str]:
    required = {
        "scope", "read_status", "external_source_verified", "account_gid",
        "currency_unit", "verified_balance", "source_count", "parsed_count",
        "transaction_gids",
    }
    if not isinstance(scope, Mapping) or set(scope) != required:
        raise PlanValidationError("W04 source_scope has unknown or missing fields")
    if (scope["scope"] != "entire_account" or scope["read_status"] != "complete"
            or scope["external_source_verified"] is not True):
        raise PlanValidationError("W04 requires a complete, externally verified account scope")
    if (scope["account_gid"] != plan["expected_account_gid"]
            or scope["currency_unit"] != plan["currency_unit"]
            or Decimal(_canonical_decimal(scope["verified_balance"], "source_scope.verified_balance"))
            != Decimal(_decimal(plan["expected_cached_account_balance"], "expected_cached_account_balance"))):
        raise PlanValidationError("W04 source scope differs from the reviewed account")
    gids = scope["transaction_gids"]
    if not isinstance(gids, list) or not gids:
        raise PlanValidationError("W04 source scope requires all account transaction GIDs")
    validated = [_text(gid, "source_scope.transaction_gids[]") for gid in gids]
    if validated != sorted(set(validated)):
        raise PlanValidationError("W04 source transaction GIDs must be unique and sorted")
    if (type(scope["source_count"]) is not int or type(scope["parsed_count"]) is not int
            or scope["source_count"] != len(validated)
            or scope["parsed_count"] != len(validated)):
        raise PlanValidationError("W04 source/parsed counts must cover the entire scope")
    return validated


def _payee_merge_key(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).split()).casefold()


def _validate_payee_merge_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Validate one reviewed W09 graph mutation without account placeholders."""
    required = {
        "contract_version", "operation_schema_version", "plan_id", "plan_digest",
        "profile_id", "model_checksum", "store_identity", "owner_uri",
        "app_identity", "capability", "created_at", "source_event_id", "merge",
    }
    if set(plan) not in (required, required - {"plan_digest"}):
        raise PlanValidationError("W09 plan has unknown or missing fields")
    if (type(plan.get("contract_version")) is not int
            or plan.get("contract_version") != CONTRACT_VERSION
            or type(plan.get("operation_schema_version")) is not int
            or plan.get("operation_schema_version") != OPERATION_SCHEMA_VERSION
            or plan.get("profile_id") != "moneywiz-2026-model-48"
            or plan.get("model_checksum") != "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ="):
        raise PlanValidationError("W09 requires the exact model-48 contract")
    for field in ("plan_id", "owner_uri", "source_event_id"):
        _text(plan.get(field), field)
    _timestamp(plan.get("created_at"), "created_at")
    store = plan.get("store_identity")
    if not isinstance(store, Mapping) or set(store) != {"store_uuid"}:
        raise PlanValidationError("W09 store identity is incomplete")
    store_uuid = _text(store["store_uuid"], "store_identity.store_uuid")
    owner_uri = _text(plan["owner_uri"], "owner_uri")
    if not re.fullmatch(rf"x-coredata://{re.escape(store_uuid)}/User/p[1-9][0-9]*", owner_uri):
        raise PlanValidationError("W09 owner URI differs from the selected store")
    app = plan.get("app_identity")
    if not isinstance(app, Mapping) or set(app) != {"bundle_id", "version", "path", "model_path"}:
        raise PlanValidationError("W09 app identity is incomplete")
    for field in app:
        _text(app[field], f"app_identity.{field}")
    merge = plan.get("merge")
    if not isinstance(merge, Mapping) or set(merge) != {
        "operation_id", "kind", "source", "survivor", "expected_references",
        "evidence_note", "approval",
    }:
        raise PlanValidationError("W09 merge has unknown or missing fields")
    _text(merge["operation_id"], "merge.operation_id")
    _text(merge["evidence_note"], "merge.evidence_note")
    kind = merge["kind"]
    if kind not in PAYEE_MERGE_CAPABILITIES or plan["capability"] != PAYEE_MERGE_CAPABILITIES[kind]:
        raise PlanValidationError("W09 merge kind and capability disagree")
    identities = []
    for role in ("source", "survivor"):
        value = merge[role]
        if not isinstance(value, Mapping) or set(value) != {"gid", "numeric_id", "name", "object_uri"}:
            raise PlanValidationError(f"W09 {role} identity is incomplete")
        for field in ("gid", "object_uri"):
            _text(value[field], f"merge.{role}.{field}")
        if not isinstance(value["name"], str) or not value["name"].strip():
            raise PlanValidationError(f"merge.{role}.name must be a nonblank string")
        numeric_id = value["numeric_id"]
        if (not isinstance(numeric_id, str) or not numeric_id.isascii()
                or not numeric_id.isdigit() or int(numeric_id) <= 0
                or value["object_uri"] != f"x-coredata://{store_uuid}/Payee/p{numeric_id}"):
            raise PlanValidationError(f"W09 {role} URI differs from its ID")
        identities.append(value)
    source, survivor = identities
    if source["gid"] == survivor["gid"] or source["numeric_id"] == survivor["numeric_id"]:
        raise PlanValidationError("W09 source and survivor must differ")
    same_name = _payee_merge_key(source["name"]) == _payee_merge_key(survivor["name"])
    if (kind == "merge_exact_payee") != same_name:
        raise PlanValidationError("W09 exact/fuzzy classification differs from payee names")
    references = merge["expected_references"]
    if not isinstance(references, list):
        raise PlanValidationError("W09 references must be a complete list")
    allowed = {"transactions", "stringHistoryItems", "scheduledTransactions",
               "connectedPaymentPlans", "infoCards"}
    keys = []
    for item in references:
        if not isinstance(item, Mapping) or set(item) != {"relationship", "entity", "object_uri"}:
            raise PlanValidationError("W09 reference has unknown or missing fields")
        relationship = _text(item["relationship"], "reference.relationship")
        entity = _text(item["entity"], "reference.entity")
        uri = _text(item["object_uri"], "reference.object_uri")
        if (relationship not in allowed or
                not re.fullmatch(rf"x-coredata://{re.escape(store_uuid)}/{re.escape(entity)}/p[1-9][0-9]*", uri)):
            raise PlanValidationError("W09 reference has an unexpected identity")
        keys.append((relationship, entity, uri))
    if keys != sorted(set(keys)):
        raise PlanValidationError("W09 references must be unique and sorted")
    approval = merge["approval"]
    if kind == "merge_exact_payee":
        if approval is not None:
            raise PlanValidationError("W09 exact merge has no fuzzy approval")
    else:
        if not isinstance(approval, Mapping) or set(approval) != {
            "user_id", "left_id", "left_name", "right_id", "right_name",
            "review_decision", "approved_canonical_id", "review_notes", "map_sha256",
        }:
            raise PlanValidationError("W09 fuzzy approval is incomplete")
        if any(not isinstance(approval[field], str) for field in (
                "left_id", "left_name", "right_id", "right_name",
                "approved_canonical_id")):
            raise PlanValidationError("W09 fuzzy map does not approve this exact pair")
        pair = {(approval["left_id"], approval["left_name"]),
                (approval["right_id"], approval["right_name"])}
        if (type(approval["user_id"]) is not int
                or approval["user_id"] != int(owner_uri.rsplit("/p", 1)[1])
                or pair != {(source["numeric_id"], source["name"]),
                            (survivor["numeric_id"], survivor["name"])}
                or approval["review_decision"] != "approved"
                or approval["approved_canonical_id"] != survivor["numeric_id"]
                or not isinstance(approval["review_notes"], str)
                or not approval["review_notes"].strip()
                or not isinstance(approval["map_sha256"], str)
                or not _HEX_DIGEST.fullmatch(approval["map_sha256"])):
            raise PlanValidationError("W09 fuzzy map does not approve this exact pair")
    digest = compute_digest(plan)
    supplied = plan.get("plan_digest")
    if supplied is not None and supplied != digest:
        raise PlanValidationError("plan_digest does not match canonical plan bytes")
    plan["plan_digest"] = digest
    return plan


def validate_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the complete v2 envelope and its strict operation union."""
    if not isinstance(payload, Mapping):
        raise PlanValidationError("plan must be a JSON object")
    plan = deepcopy(dict(payload))
    if plan.get("capability") in PAYEE_MERGE_CAPABILITIES.values():
        return _validate_payee_merge_plan(plan)
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
    w04 = plan.get("capability") in {policy[0] for policy in RECONCILE_CAPABILITIES.values()}
    if w04:
        required.add("source_scope")
    w07 = plan.get("capability") == TRANSFER_CAPABILITY
    if w07:
        required.add("destination_account")
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
    if capability not in {PAYEE_CAPABILITY, EDIT_CAPABILITY, ASSIGN_CAPABILITY,
                          ADJUST_BALANCE_CAPABILITY, DELETE_ADJUSTMENT_CAPABILITY,
                          TRANSFER_CAPABILITY,
                          *INVESTMENT_CAPABILITIES,
                          *(policy[0] for policy in RECONCILE_CAPABILITIES.values()),
                          *CREATE_CAPABILITIES}:
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
    if w07:
        destination = plan["destination_account"]
        if not isinstance(destination, Mapping) or set(destination) != {
            "account_gid", "currency_unit", "expected_cached_balance"
        }:
            raise PlanValidationError("W07 destination_account has unknown or missing fields")
        _text(destination["account_gid"], "destination_account.account_gid")
        _currency(destination["currency_unit"], "destination_account.currency_unit")
        _canonical_decimal(destination["expected_cached_balance"],
                           "destination_account.expected_cached_balance")
        if destination["account_gid"] == plan["expected_account_gid"]:
            raise PlanValidationError("W07 source and destination accounts must differ")
        _currency(plan["currency_unit"], "currency_unit")
        _canonical_decimal(plan["expected_cached_account_balance"],
                           "expected_cached_account_balance")
    scope_gids = _validate_source_scope(plan["source_scope"], plan) if w04 else []
    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        raise PlanValidationError("operations must be a nonempty list")
    operation_ids: set[str] = set()
    transaction_gids: set[str] = set()
    create_operations = 0
    adjust_operations = 0
    delete_operations = 0
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
        elif kind == "edit_transaction":
            transaction_gid = _validate_edit_operation(operation, prefix, plan)
        elif kind == "assign_payee_categories":
            transaction_gid = _validate_assign_operation(operation, prefix, plan)
        elif kind in RECONCILE_CAPABILITIES:
            transaction_gid = _validate_reconcile_operation(operation, prefix, plan)
        elif kind in CREATE_OPERATION_POLICIES:
            create_operations += 1
            transaction_gid = _validate_create_operation(operation, prefix, plan)
        elif kind == "adjust_investment_total":
            adjust_operations += 1
            transaction_gid = _validate_adjust_balance_operation(operation, prefix, plan)
        elif kind == "delete_investment_total_adjustment":
            delete_operations += 1
            transaction_gid = _validate_delete_adjustment_operation(operation, prefix, plan)
        elif kind == "replace_import_with_transfer":
            transaction_gid = _validate_transfer_operation(operation, prefix, plan)
        elif kind in INVESTMENT_POLICIES:
            transaction_gid = _validate_investment_operation(operation, prefix, plan)
        else:
            raise PlanValidationError(f"{prefix}.kind is not enabled")
        if transaction_gid in transaction_gids:
            raise PlanValidationError("operations must not target a transaction twice")
        transaction_gids.add(transaction_gid)
        if w04 and transaction_gid not in scope_gids:
            raise PlanValidationError("W04 target is absent from complete account scope")
    if (create_operations or adjust_operations or delete_operations or w07
            or plan["capability"] in INVESTMENT_CAPABILITIES) and len(operations) != 1:
        raise PlanValidationError(
            "a creation or deletion source event must contain exactly one operation"
        )
    if create_operations or adjust_operations or plan["capability"] in INVESTMENT_CAPABILITIES:
        _whole_timestamp(plan["created_at"], "created_at")
    if not create_operations and plan["capability"] not in {
        PAYEE_CAPABILITY,
        EDIT_CAPABILITY,
        ASSIGN_CAPABILITY,
        ADJUST_BALANCE_CAPABILITY,
        DELETE_ADJUSTMENT_CAPABILITY,
        TRANSFER_CAPABILITY,
        *INVESTMENT_CAPABILITIES,
        *(policy[0] for policy in RECONCILE_CAPABILITIES.values()),
    }:
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
    if plan["capability"] in PAYEE_MERGE_CAPABILITIES.values():
        receipts = result.get("operations")
        if not isinstance(receipts, list) or len(receipts) != 1 or not isinstance(receipts[0], Mapping):
            raise PlanValidationError("W09 receipt must identify one merge")
        receipt = receipts[0]
        merge = plan["merge"]
        if (set(receipt) != {"operation_id", "status", "source_payee_gid",
                             "survivor_payee_gid", "moved_references",
                             "source_absent", "survivor_present"}
                or receipt["operation_id"] != merge["operation_id"]
                or receipt["source_payee_gid"] != merge["source"]["gid"]
                or receipt["survivor_payee_gid"] != merge["survivor"]["gid"]
                or receipt["status"] != classification
                or receipt["survivor_present"] is not True):
            raise PlanValidationError("W09 receipt differs from reviewed identities")
        if success:
            if (receipt["source_absent"] is not True
                    or receipt["moved_references"] != merge["expected_references"]):
                raise PlanValidationError("W09 receipt does not prove the complete merge")
        elif (receipt["source_absent"] is not False
              or receipt["moved_references"] != []):
            raise PlanValidationError("W09 unresolved receipt claims a completed merge")
        return result
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
            operation["kind"] in CREATE_OPERATION_POLICIES | INVESTMENT_POLICIES
            and classification == "retry_safe"
        )
        transfer_without_pair = (
            operation["kind"] == "replace_import_with_transfer"
            and classification in {"retry_safe", "unknown"}
            and numeric_id is None and uri is None
        )
        adjust_without_row = (
            operation["kind"] == "adjust_investment_total"
            and classification in {"noop", "retry_safe", "unknown"}
            and numeric_id is None and uri is None
        )
        if (
            operation["kind"] == "adjust_investment_total"
            and classification == "retry_safe"
            and not adjust_without_row
        ):
            raise PlanValidationError("W05 retry-safe receipt must not claim a durable row")
        if adjust_without_row and classification == "noop" and (
            operation["expected_prior_balance"] != operation["target_balance"]
        ):
            raise PlanValidationError("W05 no-row noop requires an already matching target")
        if creation_retry_safe or transfer_without_pair:
            if numeric_id is not None or uri is not None:
                raise PlanValidationError(
                    "retry-safe creation receipt must not claim a durable identity"
                )
        elif not adjust_without_row and (
            not isinstance(numeric_id, str)
            or not numeric_id.isascii()
            or not numeric_id.isdigit()
            or int(numeric_id) <= 0
        ):
            raise PlanValidationError(
                "native operation receipt has no durable numeric identity"
            )
        if not creation_retry_safe and not adjust_without_row and not transfer_without_pair:
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
        if operation["kind"] == "delete_investment_total_adjustment" and (
            numeric_id != operation["transaction_numeric_id"]
            or uri != (
                f"x-coredata://{plan['store_identity']['store_uuid']}/"
                f"ReconcileTransaction/p{numeric_id}"
            )
        ):
            raise PlanValidationError("W06 receipt does not identify the deleted target")
        if operation["kind"] == "replace_import_with_transfer":
            details = receipt.get("transfer_details")
            if success:
                if not isinstance(details, Mapping) or set(details) != {
                    "recipient_gid", "recipient_numeric_id", "recipient_uri",
                    "old_sender_numeric_id", "old_recipient_numeric_id",
                    "reciprocal_links_verified",
                }:
                    raise PlanValidationError("W07 receipt omits the paired identity map")
                recipient_id = details["recipient_numeric_id"]
                if (not isinstance(recipient_id, str) or not recipient_id.isascii()
                        or not recipient_id.isdigit() or int(recipient_id) <= 0
                        or details["recipient_gid"] != operation["recipient_transaction_gid"]
                        or details["recipient_uri"] != (
                            f"x-coredata://{plan['store_identity']['store_uuid']}/"
                            f"TransferDepositTransaction/p{recipient_id}"
                        )
                        or details["old_sender_numeric_id"] !=
                        operation["source_old"]["transaction_numeric_id"]
                        or details["old_recipient_numeric_id"] != (
                            operation["destination_old"]["transaction_numeric_id"]
                            if operation["destination_old"] else None
                        )
                        or details["reciprocal_links_verified"] is not True):
                    raise PlanValidationError("W07 receipt pair differs from the reviewed transfer")
            elif details is not None:
                raise PlanValidationError("unverified W07 receipt claims a paired identity")
        if operation["kind"] in INVESTMENT_POLICIES:
            fields = (
                "account_mode", "cash_event_type", "investment_symbol", "holding_gid", "holding_symbol",
                "asset_type", "quantity", "unit_price", "fee", "fee_currency",
                "expected_prior_cash", "expected_final_cash", "expected_prior_units",
                "expected_final_units",
            )
            details = receipt.get("investment_details")
            if success and details != {field: operation[field] for field in fields}:
                raise PlanValidationError("W08 receipt differs from derived cash or holding state")
            if not success and details is not None:
                raise PlanValidationError("unverified W08 receipt claims investment state")
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
                    "native operation receipt violates its "
                    + (
                        "edit"
                        if operation["kind"] == "edit_transaction"
                        else "assignment"
                        if operation["kind"] == "assign_payee_categories"
                        else "creation"
                    )
                    + " postcondition"
                )
        elif receipt.get("postcondition") is not None:
            raise PlanValidationError(
                "unverified operation receipt must not claim a postcondition"
            )
    return result
