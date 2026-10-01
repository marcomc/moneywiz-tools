"""W05 contract checks for the observed investment-total shape."""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from test_transaction_create import request as creation_request
import writer_client
from compatibility import CompatibilityError
from write_plan import PlanValidationError, validate_plan, validate_result
from write_transactions import build_adjust_balance_plan


def request() -> dict:
    base = creation_request()
    base["currency_unit"] = "GBP"
    base["expected_cached_account_balance"] = "0"
    base["operation"] = {
        "operation_id": "adjust-1",
        "kind": "adjust_investment_total",
        "account_gid": base["expected_account_gid"],
        "balance_unit": "investment_total",
        "expected_prior_balance": "100.00",
        "target_balance": "99.25",
        "occurred_at": "2026-09-13T10:00:00+02:00",
    }
    return base


def receipt(plan: dict, classification: str, *, durable: bool) -> dict:
    operation = plan["operations"][0]
    result = {
        "contract_version": 2,
        "plan_id": plan["plan_id"],
        "plan_digest": plan["plan_digest"],
        "classification": classification,
        "verified": classification in {"applied", "noop"},
        "operations": [{
            "operation_id": operation["operation_id"],
            "status": classification if classification in {"applied", "noop"} else "unknown",
            "transaction_entity": operation["transaction_entity"],
            "transaction_gid": operation["transaction_gid"],
            "durable_numeric_id": "9909" if durable else None,
            "durable_uri": (
                f"x-coredata://{plan['store_identity']['store_uuid']}/ReconcileTransaction/p9909"
                if durable else None
            ),
            "old_payee_gid": None,
            "new_payee_gid": None,
            "postcondition": operation["expected_postcondition"]
            if classification in {"applied", "noop"} else None,
        }],
    }
    return result


def test_w05_plan_binds_native_entity_and_exact_delta() -> None:
    plan = build_adjust_balance_plan(request())
    operation = plan["operations"][0]
    assert operation["transaction_entity"] == "ReconcileTransaction"
    assert operation["expected_balance_delta"] == "-0.75"
    assert operation["expected_postcondition"]["target_balance"] == "99.25"
    assert validate_plan(plan) == plan


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(store_identity="invalid"),
    lambda value: value.update(currency_unit="EUR"),
    lambda value: value["operation"].update(balance_unit="investment_cash"),
    lambda value: value["operation"].update(target_balance="99.251"),
    lambda value: value["operation"].update(occurred_at="2026-09-13T10:00:00Z"),
])
def test_w05_rejects_unsupported_or_malformed_request(mutation) -> None:
    candidate = request()
    mutation(candidate)
    with pytest.raises(PlanValidationError):
        build_adjust_balance_plan(candidate)


def test_w05_receipts_require_durable_id_only_when_a_row_exists() -> None:
    plan = build_adjust_balance_plan(request())
    assert validate_result(plan, receipt(plan, "retry_safe", durable=False))
    assert validate_result(plan, receipt(plan, "unknown", durable=False))
    assert validate_result(plan, receipt(plan, "applied", durable=True))
    assert validate_result(plan, receipt(plan, "noop", durable=True))
    with pytest.raises(PlanValidationError):
        validate_result(plan, receipt(plan, "applied", durable=False))
    with pytest.raises(PlanValidationError):
        validate_result(plan, receipt(plan, "retry_safe", durable=True))


def test_w05_matching_target_noop_has_no_transaction() -> None:
    candidate = deepcopy(request())
    candidate["operation"]["target_balance"] = "100.00"
    plan = build_adjust_balance_plan(candidate)
    assert validate_result(plan, receipt(plan, "noop", durable=False))


def test_w05_client_requires_fixture_capability_for_noncanonical_store(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = build_adjust_balance_plan(request())
    checked: list[str] = []

    def reject(_store: Path, capability: str) -> None:
        checked.append(capability)
        raise CompatibilityError("blocked")

    monkeypatch.setattr(writer_client, "require_disposable_write_capability", reject)
    client = writer_client.WriterClient(Path("host"), Path("model"), Path("store"))
    with pytest.raises(writer_client.WriterClientError, match="blocked"):
        client._require_operation_capability(plan)
    assert checked == [plan["capability"]]


@pytest.mark.parametrize("currency,precision,target", [
    ("JPY", 0, "101"), ("EUR", 2, "100.01"), ("BHD", 3, "100.001"),
    ("XAU", 6, "100.000001"), ("BTC", 8, "100.00000001"),
    ("PI+35697", 8, "100.12345678"),
])
def test_aggregate_currency_metadata_binds_amounts_and_receipt(currency, precision, target) -> None:
    candidate = request()
    candidate["currency_unit"] = currency
    candidate["operation"].update(currency_precision=precision, reporting_exchange_rate="0.75", target_balance=target)
    plan = build_adjust_balance_plan(candidate)
    assert plan["operations"][0]["expected_postcondition"]["currency_precision"] == precision
    assert plan["operations"][0]["expected_postcondition"]["reporting_exchange_rate"] == "0.75"
    assert validate_result(plan, receipt(plan, "applied", durable=True))
    candidate["operation"]["target_balance"] = "100." + "0" * precision + "1"
    with pytest.raises(PlanValidationError, match="precision"):
        build_adjust_balance_plan(candidate)


@pytest.mark.parametrize("value", [True, False, 2.0, "2", None, -1, 1, 9])
def test_aggregate_precision_rejects_noninteger_or_unsupported_values(value) -> None:
    candidate = request()
    candidate["operation"].update(currency_precision=value, reporting_exchange_rate="0")
    with pytest.raises(PlanValidationError):
        build_adjust_balance_plan(candidate)


@pytest.mark.parametrize("metadata", [
    {"currency_precision": 2}, {"reporting_exchange_rate": "1"},
    {"currency_precision": 2, "reporting_exchange_rate": "-1"},
    {"currency_precision": 2, "reporting_exchange_rate": True},
])
def test_aggregate_metadata_requires_complete_nonnegative_native_contract(metadata) -> None:
    candidate = request()
    candidate["currency_unit"] = "EUR"
    candidate["operation"].update(metadata)
    with pytest.raises(PlanValidationError):
        build_adjust_balance_plan(candidate)


def test_original_gbp_contract_keeps_its_digest_and_field_shape() -> None:
    plan = build_adjust_balance_plan(request())
    assert "currency_precision" not in plan["operations"][0]
    assert "reporting_exchange_rate" not in plan["operations"][0]
    # New metadata must never silently rewrite an already reviewed old plan.
    explicit = request()
    explicit["operation"].update(currency_precision=2, reporting_exchange_rate="0")
    assert build_adjust_balance_plan(explicit)["plan_digest"] != plan["plan_digest"]


def test_aggregate_receipt_precision_is_an_exact_integer() -> None:
    candidate = request()
    candidate["currency_unit"] = "JPY"
    candidate["operation"].update(currency_precision=0, reporting_exchange_rate="0.75", target_balance="101")
    plan = build_adjust_balance_plan(candidate)
    result = receipt(plan, "applied", durable=True)
    result["operations"][0]["postcondition"]["currency_precision"] = False
    with pytest.raises(PlanValidationError, match="exact currency precision"):
        validate_result(plan, result)
