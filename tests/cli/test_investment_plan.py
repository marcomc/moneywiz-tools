"""W08 investment plans bind one cash event or an existing holding."""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from test_transaction_create import request as creation_request
from write_plan import PlanValidationError, validate_plan, validate_result
from write_transactions import build_investment_plan


def request(kind: str = "investment_buy", *, aggregate: bool = False) -> dict:
    value = creation_request()
    value["expected_cached_account_balance"] = "0"
    value["expected_account_gid"] = "investment-1"
    value["operation"] = {
        "operation_id": "investment-event-1",
        "kind": kind,
        "account_gid": "investment-1",
        "amount": {
            "investment_income": "2", "investment_expense": "-2",
            "investment_buy": "-11", "investment_sell": "9",
        }[kind],
        "occurred_at": "2026-09-13T09:30:00+02:00",
        "payee_gid": "payee-1",
        "category_splits": (
            [{"category_gid": "income", "amount": "2"}] if kind == "investment_income"
            else [{"category_gid": "expense", "amount": "-2"}]
            if kind == "investment_expense" else []
        ),
        "tag_gids": [],
        "note": "Synthetic W08",
        "account_mode": "aggregate" if aggregate else "units",
        "cash_event_type": (
            "dividend" if kind == "investment_income" else "fee"
            if kind == "investment_expense" else None
        ),
        "investment_symbol": None,
        "holding_gid": None if kind.endswith(("income", "expense")) else "holding-1",
        "holding_symbol": None if kind.endswith(("income", "expense")) else "TEST",
        "asset_type": None if kind.endswith(("income", "expense")) else 1,
        "quantity": "0" if kind.endswith(("income", "expense")) else "2",
        "unit_price": "0" if kind.endswith(("income", "expense")) else "5",
        "fee": "0" if kind.endswith(("income", "expense")) else "1",
        "fee_currency": "EUR",
        "expected_prior_cash": "100" if aggregate else "89",
        "expected_prior_units": None if kind.endswith(("income", "expense")) else "12",
    }
    return value


@pytest.mark.parametrize("kind", [
    "investment_income", "investment_expense", "investment_buy", "investment_sell",
])
def test_w08_plan_is_strict_and_deterministic(kind: str) -> None:
    plan = build_investment_plan(request(kind, aggregate=kind == "investment_income"))
    operation = plan["operations"][0]
    assert validate_plan(plan) == plan
    assert operation["expected_final_cash"] == {
        "investment_income": "102", "investment_expense": "87",
        "investment_buy": "78", "investment_sell": "98",
    }[kind]
    if kind.endswith(("buy", "sell")):
        assert operation["expected_final_units"] == ("14" if kind.endswith("buy") else "10")


@pytest.mark.parametrize("change", [
    lambda value: value["operation"].update(fee_currency="GBP"),
    lambda value: value["operation"].update(amount="-10"),
    lambda value: value["operation"].update(holding_gid=None),
    lambda value: value["operation"].update(account_mode="aggregate"),
    lambda value: value["operation"].update(quantity="0"),
    lambda value: value["operation"].update(unit_price="0"),
    lambda value: value["operation"].update(fee="-1"),
])
def test_w08_rejects_unreviewed_trade(change) -> None:
    value = deepcopy(request())
    change(value)
    with pytest.raises(PlanValidationError):
        build_investment_plan(value)


def test_w08_receipt_requires_derived_state() -> None:
    plan = build_investment_plan(request())
    operation = plan["operations"][0]
    numeric_id = "12"
    result = {
        "contract_version": 2,
        "plan_id": plan["plan_id"],
        "plan_digest": plan["plan_digest"],
        "classification": "applied",
        "verified": True,
        "operations": [{
            "operation_id": operation["operation_id"],
            "status": "applied",
            "transaction_entity": operation["transaction_entity"],
            "transaction_gid": operation["transaction_gid"],
            "durable_numeric_id": numeric_id,
            "durable_uri": (
                f"x-coredata://{plan['store_identity']['store_uuid']}/"
                f"{operation['transaction_entity']}/p{numeric_id}"
            ),
            "old_payee_gid": None,
            "new_payee_gid": None,
            "postcondition": operation["expected_postcondition"],
            "investment_details": {field: operation[field] for field in (
                "account_mode", "cash_event_type", "investment_symbol", "holding_gid", "holding_symbol",
                "asset_type", "quantity", "unit_price", "fee", "fee_currency",
                "expected_prior_cash", "expected_final_cash", "expected_prior_units",
                "expected_final_units",
            )},
        }],
    }
    assert validate_result(plan, result) == result
    result["operations"][0]["investment_details"]["expected_final_units"] = "13"
    with pytest.raises(PlanValidationError, match="W08 receipt"):
        validate_result(plan, result)


def first_buy_request(*, holding_type: str = "Stock") -> dict:
    value = request()
    value["operation"].update(kind="investment_buy_new_holding", holding_gid=None,
                              holding_symbol="FIRST", asset_type=0, expected_prior_units="0",
                              holding_type=holding_type, holding_description="Synthetic first holding")
    return value


def test_first_buy_derives_native_account_symbol_gid() -> None:
    plan = build_investment_plan(first_buy_request())
    operation = plan["operations"][0]
    assert plan["capability"] == "write.investment-buy-new-holding"
    assert operation["holding_gid"] == "investment-1-FIRST-0"
    assert operation["expected_final_units"] == "2"
    assert operation["expected_final_cash"] == "78"
    assert validate_plan(plan) == plan


@pytest.mark.parametrize("field,value", [
    ("holding_gid", "existing"), ("holding_type", "Unknown"),
    ("holding_type", None), ("holding_type", []),
    ("holding_description", " "), ("holding_description", True),
    ("holding_description", " name"), ("holding_description", "name\u00a0"),
    ("holding_description", "\u001c"), ("holding_symbol", None),
    ("holding_symbol", " FIRST"), ("asset_type", 1), ("asset_type", False),
    ("expected_prior_units", "1"), ("account_mode", "aggregate"),
])
def test_first_buy_request_rejects_unreviewed_creation(field, value) -> None:
    payload = first_buy_request()
    payload["operation"][field] = value
    with pytest.raises(PlanValidationError):
        build_investment_plan(payload)


def test_first_buy_rejects_sub_native_quantity_precision() -> None:
    payload = first_buy_request()
    payload["operation"].update(quantity="0.000000001", unit_price="10000000", amount="-1.01")
    with pytest.raises(PlanValidationError, match="first Buy"):
        build_investment_plan(payload)
