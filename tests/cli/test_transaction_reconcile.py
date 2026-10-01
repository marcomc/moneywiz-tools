"""W04 plans require complete account evidence and exact native flag guards."""

from copy import deepcopy
import json

import pytest

from test_transaction_create import request as create_request
from write_plan import PlanValidationError, validate_plan, validate_result
from write_transactions import build_reconcile_plan, main


def request(kind: str = "reconcile_transaction") -> dict:
    payload = create_request()
    payload.pop("operation")
    payload["source_scope"] = {
        "scope": "entire_account",
        "read_status": "complete",
        "external_source_verified": True,
        "account_gid": payload["expected_account_gid"],
        "currency_unit": payload["currency_unit"],
        "verified_balance": "100",
        "source_count": 2,
        "parsed_count": 2,
        "transaction_gids": ["deposit-1", "withdraw-1"],
    }
    payload["operations"] = [{
        "operation_id": "w04-1",
        "kind": kind,
        "transaction_entity": "WithdrawTransaction",
        "transaction_gid": "withdraw-1",
        "account_gid": payload["expected_account_gid"],
        "expected_reconciled": kind == "unreconcile_transaction",
        "expected_native_status": 1,
        "expected_native_flags": 1,
        "correction_reason": "Incorrect external source" if kind == "unreconcile_transaction" else None,
    }]
    return payload


@pytest.mark.parametrize("kind,capability", [
    ("reconcile_transaction", "write.reconcile"),
    ("unreconcile_transaction", "write.unreconcile"),
])
def test_builds_separate_guarded_capabilities(kind, capability):
    raw = request(kind)
    original = deepcopy(raw)
    plan = build_reconcile_plan(raw, kind=kind)
    assert raw == original
    assert plan["capability"] == capability
    assert plan["source_scope"]["verified_balance"] == "100"
    assert plan["operations"][0]["allowed_changed_fields"] == ["reconciled"]
    assert validate_plan(plan) == plan


@pytest.mark.parametrize("change", [
    lambda p: p["source_scope"].update(external_source_verified=False),
    lambda p: p["source_scope"].update(read_status="partial"),
    lambda p: p["source_scope"].update(source_count=1),
    lambda p: p["source_scope"].update(transaction_gids=["withdraw-1", "deposit-1"]),
    lambda p: p["source_scope"].update(verified_balance="invalid"),
    lambda p: p["operations"][0].update(expected_reconciled=True),
    lambda p: p["operations"][0].update(expected_native_flags=-1),
    lambda p: p["operations"][0].update(expected_native_status=3),
    lambda p: p["operations"][0].update(transaction_entity="TransferWithdrawTransaction"),
    lambda p: p["operations"][0].update(transaction_gid="missing"),
])
def test_rejects_incomplete_scope_or_ambiguous_transition(change):
    raw = request()
    change(raw)
    with pytest.raises(PlanValidationError):
        build_reconcile_plan(raw, kind="reconcile_transaction")


def test_receipt_requires_exact_flags_and_postcondition():
    plan = build_reconcile_plan(request(), kind="reconcile_transaction")
    operation = plan["operations"][0]
    result = {
        "contract_version": 2, "plan_id": plan["plan_id"],
        "plan_digest": plan["plan_digest"], "classification": "applied",
        "verified": True, "operations": [{
            "operation_id": operation["operation_id"], "status": "applied",
            "transaction_entity": operation["transaction_entity"],
            "transaction_gid": operation["transaction_gid"],
            "durable_uri": "x-coredata://fixture-store/WithdrawTransaction/p1",
            "durable_numeric_id": "1", "old_payee_gid": None,
            "new_payee_gid": None,
            "postcondition": operation["expected_postcondition"],
        }],
    }
    assert validate_result(plan, result) == result
    result["operations"][0]["postcondition"] = {
        **operation["expected_postcondition"], "native_flags": 0,
    }
    with pytest.raises(PlanValidationError):
        validate_result(plan, result)


def test_cli_writes_reviewable_reconcile_plan(tmp_path, capsys):
    request_path, plan_path = tmp_path / "request.json", tmp_path / "plan.json"
    request_path.write_text(json.dumps(request()), encoding="utf-8")
    assert main(["reconcile", "--request", str(request_path), "--plan", str(plan_path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["plan_digest"] == json.loads(plan_path.read_text())["plan_digest"]
    assert plan_path.stat().st_mode & 0o777 == 0o600
