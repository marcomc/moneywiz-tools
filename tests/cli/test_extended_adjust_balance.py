"""Explicit native W05 balance units and their strict plan/receipt boundaries."""

from copy import deepcopy

import pytest

from test_adjust_balance import request as aggregate_request, receipt
from write_plan import PlanValidationError, validate_plan, validate_result
from write_transactions import build_adjust_balance_plan


def request(kind="adjust_account_balance", currency="EUR"):
    value = aggregate_request()
    value["currency_unit"] = currency
    unit = {
        "adjust_account_balance": "account_balance",
        "adjust_investment_cash": "investment_cash",
        "adjust_asset_quantity": "asset_quantity",
    }[kind]
    value["operation"].update(
        kind=kind, balance_unit=unit, description="TEST W05 balance",
        reporting_exchange_rate="1", expected_prior_balance="100", target_balance="100.01",
    )
    if kind == "adjust_asset_quantity":
        value["operation"].update(
            holding_gid="w05-holding", holding_symbol="ETH", asset_type=1, expected_prior_cash="100",
            reporting_exchange_rate="0", expected_prior_balance="1.015", target_balance="1.01500001",
        )
    return value


@pytest.mark.parametrize("currency", ["GBP", "EUR", "USD", "CAD"])
@pytest.mark.parametrize("kind", ["adjust_account_balance", "adjust_investment_cash", "adjust_asset_quantity"])
def test_w05_extended_plan_and_receipts(kind, currency):
    plan = build_adjust_balance_plan(request(kind, currency))
    assert validate_plan(plan) == plan
    assert validate_result(plan, receipt(plan, "retry_safe", durable=False))
    assert validate_result(plan, receipt(plan, "applied", durable=True))
    with pytest.raises(PlanValidationError):
        validate_result(plan, receipt(plan, "applied", durable=False))
    no_op = request(kind, currency)
    no_op["operation"]["target_balance"] = no_op["operation"]["expected_prior_balance"]
    matching = build_adjust_balance_plan(no_op)
    assert validate_result(matching, receipt(matching, "noop", durable=False))


@pytest.mark.parametrize("mutation", [
    lambda v: v["operation"].update(balance_unit="investment_total"),
    lambda v: v["operation"].update(description="\x1c"),
    lambda v: v["operation"].update(description=" TEST"),
    lambda v: v["operation"].update(description="TEST\u00a0"),
    lambda v: v["operation"].update(reporting_exchange_rate=True),
    lambda v: v["operation"].update(reporting_exchange_rate="-1"),
    lambda v: v["operation"].update(target_balance="100.001"),
    lambda v: v.update(currency_unit="JPY"),
    lambda v: v["operation"].update(holding_gid="unexpected"),
    lambda v: v["operation"].update(kind=[]),
    lambda v: v["operation"].update(kind={}),
])
def test_w05_extended_rejects_invalid_request(mutation):
    value = request()
    mutation(value)
    with pytest.raises(PlanValidationError):
        build_adjust_balance_plan(value)


@pytest.mark.parametrize("field,value", [
    ("holding_gid", "\x1c"), ("holding_symbol", "\x1f"),
    ("expected_prior_cash", 100), ("expected_prior_balance", "-1"),
    ("target_balance", "-1"), ("target_balance", "1.015000001"),
    ("reporting_exchange_rate", "1"),
    ("asset_type", True), ("asset_type", "0"), ("asset_type", 2),
])
def test_w05_quantity_rejects_invalid_identity_units_or_cash(field, value):
    candidate = request("adjust_asset_quantity")
    candidate["operation"][field] = value
    with pytest.raises(PlanValidationError):
        build_adjust_balance_plan(candidate)


def test_w05_postcondition_and_envelope_cannot_change_variant():
    plan = build_adjust_balance_plan(request())
    candidate = deepcopy(plan)
    candidate.pop("plan_digest")
    candidate["capability"] = "write.adjust-investment-cash"
    with pytest.raises(PlanValidationError):
        validate_plan(candidate)
    candidate = deepcopy(plan)
    candidate.pop("plan_digest")
    candidate["operations"][0]["description"] = "changed"
    with pytest.raises(PlanValidationError):
        validate_plan(candidate)


@pytest.mark.parametrize("value", [True, 1.0])
def test_w05_quantity_postcondition_requires_exact_asset_type(value):
    plan = build_adjust_balance_plan(request("adjust_asset_quantity"))
    candidate = deepcopy(plan)
    candidate.pop("plan_digest")
    candidate["operations"][0]["expected_postcondition"]["asset_type"] = value
    with pytest.raises(PlanValidationError):
        validate_plan(candidate)
    result = receipt(plan, "applied", durable=True)
    result["operations"][0]["postcondition"] = deepcopy(result["operations"][0]["postcondition"])
    result["operations"][0]["postcondition"]["asset_type"] = value
    with pytest.raises(PlanValidationError):
        validate_result(plan, result)
