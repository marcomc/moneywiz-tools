"""W02 plans preserve exact identity and reject unowned mutations before I/O."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import write_transactions
import writer_client
from test_transaction_create import request as create_request
from write_plan import PlanValidationError, validate_plan, validate_result


def request(field="note", previous=None, value="Edited note"):
    payload = create_request()
    payload["operation"] = {
        "operation_id": "edit-1",
        "kind": "edit_transaction",
        "transaction_entity": "DepositTransaction",
        "transaction_gid": "existing-exact-gid",
        "account_gid": payload["expected_account_gid"],
        "changes": {field: value},
        "expected_prior": {field: previous},
        "correction_mode": "reject_reconciled",
    }
    return payload


@pytest.mark.parametrize(
    "field,previous,value,native",
    [
        ("note", None, "Updated", ["notes"]),
        ("description", "Imported description", "Corrected description", ["desc"]),
        ("checkbook_number", "001", None, ["checkbookNumber"]),
        (
            "occurred_at",
            "2026-09-12T10:00:00+02:00",
            "2026-09-13T10:00:00+02:00",
            ["date"],
        ),
        ("amount", "12.50", "15.00", ["amount", "originalAmount"]),
    ],
)
def test_allowlist_and_exact_identity(field, previous, value, native):
    raw = request(field, previous, value)
    original = deepcopy(raw)
    plan = write_transactions.build_edit_plan(raw)
    operation = plan["operations"][0]
    assert raw == original
    assert operation["transaction_gid"] == "existing-exact-gid"
    assert operation["allowed_changed_fields"] == native
    assert operation["expected_balance_delta"] == ("2.5" if field == "amount" else "0")
    assert operation["expected_postcondition"] == {
        "fields": operation["changes"],
        "expected_balance_delta": operation["expected_balance_delta"],
    }
    assert validate_plan(plan) == plan


@pytest.mark.parametrize(
    "field",
    [
        "account_gid",
        "currency_unit",
        "originalAmount",
        "payee_gid",
        "tag_gids",
        "category_splits",
        "reconciled",
        "cleared",
        "pending",
        "source_event_id",
        "gid",
        "unknown",
    ],
)
def test_rejects_unowned_fields(field):
    with pytest.raises(PlanValidationError, match="supported W02 fields"):
        write_transactions.build_edit_plan(request(field))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda op: op.update(expected_prior={}),
        lambda op: op.update(expected_prior={"note": None, "description": None}),
        lambda op: op.update(changes={}),
        lambda op: op.update(correction_mode="correct_reconciled"),
        lambda op: op.update(transaction_entity="TransferDepositTransaction"),
        lambda op: op.update(transaction_entity="ReconcileTransaction"),
        lambda op: op.update(transaction_entity="InvestmentBuyTransaction"),
        lambda op: op.update(transaction_entity="Transaction"),
        lambda op: op.update(account_gid="another-account"),
        lambda op: op.update(changes={"note": None}),
        lambda op: op.update(changes={"note": ""}),
        lambda op: op.update(changes={"note": " leading"}),
        lambda op: op.update(changes={"note": 5}),
    ],
)
def test_invalid_edit_requests_fail_closed(mutate):
    payload = request()
    mutate(payload["operation"])
    with pytest.raises(PlanValidationError):
        write_transactions.build_edit_plan(payload)


@pytest.mark.parametrize(
    "previous,value",
    [
        ("1", "0"),
        ("1", "-1"),
        ("0", "1"),
        ("1", "1.00"),
        ("1", "NaN"),
        ("1", "0.1234567890123456789"),
    ],
)
def test_amount_requires_nonzero_sign_preserving_exact_native_values(previous, value):
    with pytest.raises(PlanValidationError):
        write_transactions.build_edit_plan(request("amount", previous, value))


@pytest.mark.parametrize(
    "entity,previous,value,delta",
    [
        ("DepositTransaction", "10", "8", "-2"),
        ("WithdrawTransaction", "-10", "-12", "-2"),
        ("RefundTransaction", "5", "6", "1"),
    ],
)
def test_amount_entities(entity, previous, value, delta):
    payload = request("amount", previous, value)
    payload["operation"]["transaction_entity"] = entity
    assert (
        write_transactions.build_edit_plan(payload)["operations"][0][
            "expected_balance_delta"
        ]
        == delta
    )


@pytest.mark.parametrize(
    "previous,value",
    [
        ("2026-09-12T10:00:00+02:00", "2026-09-13T10:00:00Z"),
        ("2026-09-12T10:00:00.1+02:00", "2026-09-13T10:00:00+02:00"),
        ("2026-09-12T10:00:00+02:00", "2026-09-12T10:00:00+02:00"),
    ],
)
def test_dates_need_exact_whole_seconds_and_timezone(previous, value):
    with pytest.raises(PlanValidationError):
        write_transactions.build_edit_plan(request("occurred_at", previous, value))


@pytest.mark.parametrize(
    "field,value",
    [
        ("allowed_changed_fields", ["notes", "desc"]),
        ("expected_balance_delta", "1"),
        (
            "expected_postcondition",
            {"fields": {"note": "Other"}, "expected_balance_delta": "0"},
        ),
        ("owner_uri", "x-coredata://another/User/p1"),
        ("currency_unit", "USD"),
        ("timezone", "UTC"),
        ("source_event_id", "different-event"),
    ],
)
def test_plan_revalidates_derived_fields(field, value):
    plan = write_transactions.build_edit_plan(request())
    plan.pop("plan_digest")
    plan["operations"][0][field] = value
    with pytest.raises(PlanValidationError):
        validate_plan(plan)


def test_multiple_exact_targets_and_kind_mixing():
    plan = write_transactions.build_edit_plan(request())
    plan.pop("plan_digest")
    second = deepcopy(plan["operations"][0])
    second.update(operation_id="edit-2", transaction_gid="second-gid")
    plan["operations"].append(second)
    assert len(validate_plan(plan)["operations"]) == 2
    second["transaction_gid"] = "existing-exact-gid"
    with pytest.raises(PlanValidationError, match="twice"):
        validate_plan(plan)


def test_cli_planning_never_opens_store_and_plan_is_immutable(tmp_path, capsys):
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request()))
    plan = tmp_path / "edit.json"
    absent = tmp_path / "not-a-database.sqlite"
    arguments = [
        "--db",
        str(absent),
        "edit",
        "--request",
        str(source),
        "--plan",
        str(plan),
    ]
    assert write_transactions.main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "planned"
    assert plan.stat().st_mode & 0o777 == 0o600
    assert not absent.exists()
    assert write_transactions.main(arguments) == 2
    assert "cannot create immutable plan" in capsys.readouterr().err


def test_edit_client_enforces_disposable_boundary(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        writer_client,
        "require_disposable_write_capability",
        lambda db, cap: calls.append((db, cap)),
    )
    client = writer_client.WriterClient(
        Path("writer"), Path("model"), tmp_path / "fixture"
    )
    client._require_operation_capability(write_transactions.build_edit_plan(request()))
    assert calls == [(tmp_path / "fixture", "write.edit-transaction")]


def test_result_requires_exact_postcondition():
    plan = write_transactions.build_edit_plan(request())
    op = plan["operations"][0]
    receipt = {
        "contract_version": 2,
        "plan_id": plan["plan_id"],
        "plan_digest": plan["plan_digest"],
        "classification": "applied",
        "verified": True,
        "operations": [
            {
                "operation_id": op["operation_id"],
                "transaction_gid": op["transaction_gid"],
                "transaction_entity": op["transaction_entity"],
                "status": "applied",
                "durable_numeric_id": "9",
                "durable_uri": "x-coredata://fixture-store/Transaction/p9",
                "postcondition": op["expected_postcondition"],
            }
        ],
    }
    assert validate_result(plan, receipt) == receipt
    receipt["operations"][0]["postcondition"] = {
        "fields": {"note": "Other"},
        "expected_balance_delta": "0",
    }
    with pytest.raises(PlanValidationError, match="postcondition"):
        validate_result(plan, receipt)
