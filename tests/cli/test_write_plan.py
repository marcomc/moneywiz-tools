from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import write_plan


def plan() -> dict[str, object]:
    return {
        "contract_version": 2,
        "operation_schema_version": 1,
        "plan_id": "plan-1",
        "profile_id": "profile",
        "model_checksum": "checksum",
        "store_identity": {"store_uuid": "store"},
        "owner_uri": "x-coredata://owner",
        "app_identity": {
            "bundle_id": "com.moneywiz.personalfinance",
            "version": "2026.1",
            "path": "/MoneyWiz.app",
            "model_path": "/model",
        },
        "created_at": "2026-09-13T10:00:00+00:00",
        "timezone": "Europe/Rome",
        "source_interval": {
            "start": "2026-09-01T00:00:00+02:00",
            "end": "2026-09-02T00:00:00+02:00",
        },
        "source_evidence_refs": ["synthetic://evidence/1"],
        "capability": "write.reassign-payees-by-id",
        "source_event_id": "event-1",
        "expected_account_gid": "account-1",
        "expected_cached_account_balance": "12.50",
        "currency_unit": "EUR",
        "operations": [
            {
                "operation_id": "op-1",
                "kind": "reassign_payee",
                "capability": "write.reassign-payees-by-id",
                "transaction_entity": "WithdrawTransaction",
                "transaction_gid": "tx-1",
                "expected_old_payee_gid": None,
                "target_payee_gid": "payee-1",
                "owner_uri": "x-coredata://owner",
                "source_event_id": "event-1",
                "expected_postcondition": {"payee_gid": "payee-1"},
                "allowed_changed_fields": ["payee"],
            }
        ],
    }


def test_validation_adds_stable_canonical_digest() -> None:
    first = write_plan.validate_plan(plan())
    reordered = dict(reversed(list(plan().items())))
    assert first["plan_digest"] == write_plan.compute_digest(reordered)


def test_validation_rejects_future_operation() -> None:
    payload = plan()
    payload["operations"][0]["kind"] = "create_transaction"  # type: ignore[index]
    with pytest.raises(write_plan.PlanValidationError, match="not enabled"):
        write_plan.validate_plan(payload)


def test_validation_rejects_digest_tampering() -> None:
    payload = write_plan.validate_plan(plan())
    payload["expected_cached_account_balance"] = "13.50"
    with pytest.raises(write_plan.PlanValidationError, match="does not match"):
        write_plan.validate_plan(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [("expected_cached_account_balance", "1e2"), ("contract_version", True)],
)
def test_validation_rejects_native_incompatible_scalars(
    field: str, value: object
) -> None:
    payload = plan()
    payload[field] = value
    with pytest.raises(write_plan.PlanValidationError):
        write_plan.validate_plan(payload)


def test_validation_rejects_extra_nested_key_and_operation_identity_drift() -> None:
    payload = plan()
    payload["store_identity"]["unexpected"] = "x"  # type: ignore[index]
    with pytest.raises(write_plan.PlanValidationError, match="store_identity"):
        write_plan.validate_plan(payload)
    payload = plan()
    payload["operations"][0]["owner_uri"] = "x-coredata://other"  # type: ignore[index]
    with pytest.raises(write_plan.PlanValidationError, match="owner_uri"):
        write_plan.validate_plan(payload)
