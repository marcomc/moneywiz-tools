"""W03 plans require exact prior relationships and complete replacement totals."""

from copy import deepcopy
import json

import pytest

from test_transaction_create import request as create_request
from write_plan import PlanValidationError, validate_plan, validate_result
from write_transactions import build_assign_plan, main


def request() -> dict:
    payload = create_request()
    payload["operation"] = {
        "operation_id": "assign-1",
        "kind": "assign_payee_categories",
        "transaction_entity": "WithdrawTransaction",
        "transaction_gid": "w02-categorized",
        "account_gid": payload["expected_account_gid"],
        "amount": "-4",
        "expected_assignments": {
            "payee_gid": "w01-payee",
            "category_splits": [{"category_gid": "w01-category", "amount": "-4"}],
        },
        "target": {
            "payee_gid": "w03-payee",
            "category_splits": [{"category_gid": "w03-category", "amount": "-4"}],
        },
        "replacement_mode": "replace",
    }
    return payload


def test_builds_exact_assignment_plan_without_mutating_request():
    raw = request()
    original = deepcopy(raw)
    plan = build_assign_plan(raw)
    assert raw == original
    operation = plan["operations"][0]
    assert operation["capability"] == "write.assign-payee-categories"
    assert operation["allowed_changed_fields"] == ["payee", "categoriesAssigments"]
    assert operation["expected_balance_delta"] == "0"
    assert operation["expected_postcondition"] == {
        **operation["target"], "expected_balance_delta": "0",
    }
    assert validate_plan(plan) == plan


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["operation"].update(amount="-5"),
        lambda p: p["operation"]["target"].update(category_splits=[
            {"category_gid": "w03-category", "amount": "-3"}
        ]),
        lambda p: p["operation"]["target"].update(category_splits=[
            {"category_gid": "w03-category", "amount": "4"}
        ]),
        lambda p: p["operation"].update(replacement_mode="append"),
        lambda p: p["operation"].update(transaction_entity="TransferWithdrawTransaction"),
        lambda p: p["operation"].update(account_gid="another-account"),
        lambda p: p["operation"].update(target=p["operation"]["expected_assignments"]),
        lambda p: p["operation"]["target"].update(extra=True),
        lambda p: p["operation"]["target"].update(category_splits=[{"category_gid": 12, "amount": "-4"}]),
        lambda p: p["operation"]["target"].update(category_splits=[{"category_gid": "w03-category"}]),
    ],
)
def test_rejects_invalid_or_ambiguous_replacements(change):
    payload = request()
    change(payload)
    with pytest.raises(PlanValidationError):
        build_assign_plan(payload)


def test_revalidates_derived_contract_and_receipt():
    plan = build_assign_plan(request())
    plan.pop("plan_digest")
    plan["operations"][0]["expected_postcondition"]["payee_gid"] = "other"
    with pytest.raises(PlanValidationError):
        validate_plan(plan)
    good = build_assign_plan(request())
    result = {
        "contract_version": 2,
        "plan_id": good["plan_id"],
        "plan_digest": good["plan_digest"],
        "classification": "applied",
        "verified": True,
        "operations": [{
            "operation_id": "assign-1", "status": "applied",
            "transaction_entity": "WithdrawTransaction",
            "transaction_gid": "w02-categorized",
            "durable_uri": f"x-coredata://{good['store_identity']['store_uuid']}/WithdrawTransaction/p1",
            "durable_numeric_id": "1", "old_payee_gid": None,
            "new_payee_gid": None,
            "postcondition": {**good["operations"][0]["target"], "expected_balance_delta": "0"},
        }],
    }
    assert validate_result(good, result) == result
    result["operations"][0]["postcondition"]["category_splits"] = []
    with pytest.raises(PlanValidationError):
        validate_result(good, result)


def test_assign_cli_writes_immutable_plan_without_opening_store(tmp_path, capsys):
    request_path = tmp_path / "request.json"
    plan_path = tmp_path / "plan.json"
    request_path.write_text(json.dumps(request()), encoding="utf-8")
    assert main(["assign", "--request", str(request_path), "--plan", str(plan_path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["plan_digest"] == json.loads(plan_path.read_text())["plan_digest"]
    assert plan_path.stat().st_mode & 0o777 == 0o600
