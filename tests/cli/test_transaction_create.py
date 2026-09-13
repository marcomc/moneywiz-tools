"""W01 transaction creation plans are strict, deterministic, and read-only."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import write_transactions
import writer_client
from write_plan import PlanValidationError, validate_plan, validate_result
from writer_client import WriterClient


def request(kind: str = "create_income") -> dict[str, object]:
    amount = "25.50" if kind != "create_expense" else "-25.50"
    refund_reference = (
        {
            "original_transaction_entity": "WithdrawTransaction",
            "original_transaction_gid": "original-withdrawal",
        }
        if kind == "create_refund"
        else None
    )
    return {
        "plan_id": "w01-plan",
        "profile_id": "moneywiz-2026-model-48",
        "model_checksum": "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ=",
        "store_identity": {"store_uuid": "fixture-store"},
        "owner_uri": "x-coredata://fixture-store/User/p1",
        "app_identity": {
            "bundle_id": "com.moneywiz.personalfinance",
            "version": "2026.32.1",
            "path": "/Applications/MoneyWiz.app",
            "model_path": "/Applications/MoneyWiz.app/model-48.mom",
        },
        "created_at": "2026-09-13T10:00:00+02:00",
        "timezone": "Europe/Rome",
        "source_interval": {
            "start": "2026-09-13T00:00:00+02:00",
            "end": "2026-09-14T00:00:00+02:00",
        },
        "source_evidence_refs": ["synthetic://w01/source-row-1"],
        "source_event_id": "source-row-1",
        "expected_account_gid": "account-1",
        "expected_cached_account_balance": "100.00",
        "currency_unit": "EUR",
        "operation": {
            "operation_id": "create-1",
            "kind": kind,
            "account_gid": "account-1",
            "amount": amount,
            "occurred_at": "2026-09-13T09:30:00+02:00",
            "payee_gid": "payee-1",
            "category_splits": [{"category_gid": "category-b", "amount": amount}],
            "tag_gids": ["tag-b", "tag-a"],
            "note": "Synthetic W01 fixture",
            "refund_reference": refund_reference,
        },
    }


@pytest.mark.parametrize(
    ("kind", "capability", "entity", "sign"),
    [
        ("create_income", "write.create-income", "DepositTransaction", 1),
        ("create_expense", "write.create-expense", "WithdrawTransaction", -1),
        ("create_refund", "write.create-refund", "RefundTransaction", 1),
    ],
)
def test_builder_emits_strict_kind_contract(
    kind: str, capability: str, entity: str, sign: int
) -> None:
    plan = write_transactions.build_plan(request(kind))
    operation = plan["operations"][0]

    assert plan["capability"] == capability
    assert operation["transaction_entity"] == entity
    assert operation["capability"] == capability
    assert (float(operation["amount"]) > 0) is (sign > 0)
    assert operation["amount"] in {"25.5", "-25.5"}
    assert operation["expected_balance_delta"] == operation["amount"]
    assert (
        operation["expected_postcondition"]["transaction_gid"]
        == operation["transaction_gid"]
    )
    assert operation["category_splits"][0]["category_gid"] == "category-b"
    assert operation["tag_gids"] == ["tag-a", "tag-b"]


def test_source_identity_is_stable_across_plan_operation_and_kind_changes() -> None:
    income_request = request()
    changed = request("create_expense")
    changed["plan_id"] = "another-plan"
    changed["operation"]["operation_id"] = "another-operation"

    income = write_transactions.build_plan(income_request)
    expense = write_transactions.build_plan(changed)

    assert (
        income["operations"][0]["transaction_gid"]
        == expense["operations"][0]["transaction_gid"]
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["operation"].update(amount="-1.00"),
            "wrong sign",
        ),
        (
            lambda value: value.update(currency_unit="eur"),
            "canonical three-letter currency",
        ),
        (
            lambda value: value["operation"].update(
                occurred_at="2026-09-13T09:30:00+00:00"
            ),
            "offset does not match timezone",
        ),
        (
            lambda value: value["operation"].update(
                category_splits=[{"category_gid": "category-a", "amount": "1.00"}]
            ),
            "must sum",
        ),
        (
            lambda value: value["operation"].update(refund_reference={}),
            "only valid for refunds",
        ),
    ],
)
def test_builder_rejects_ambiguous_or_incoherent_fields(mutate, message: str) -> None:
    payload = request()
    mutate(payload)
    with pytest.raises(PlanValidationError, match=message):
        write_transactions.build_plan(payload)


def test_validator_rejects_tampered_gid_and_postcondition() -> None:
    plan = write_transactions.build_plan(request())
    tampered_gid = deepcopy(plan)
    tampered_gid.pop("plan_digest")
    tampered_gid["operations"][0]["transaction_gid"] = "another-gid"
    tampered_gid["operations"][0]["expected_postcondition"]["transaction_gid"] = (
        "another-gid"
    )
    with pytest.raises(PlanValidationError, match="not deterministic"):
        validate_plan(tampered_gid)

    tampered_postcondition = deepcopy(plan)
    tampered_postcondition.pop("plan_digest")
    tampered_postcondition["operations"][0]["expected_postcondition"]["note"] = (
        "different"
    )
    with pytest.raises(PlanValidationError, match="exactly match"):
        validate_plan(tampered_postcondition)


def test_validator_requires_canonical_amount_and_whole_second_timestamp() -> None:
    plan = write_transactions.build_plan(request())
    noncanonical = deepcopy(plan)
    noncanonical.pop("plan_digest")
    operation = noncanonical["operations"][0]
    operation["amount"] = "25.50"
    operation["expected_balance_delta"] = "25.50"
    operation["expected_postcondition"]["amount"] = "25.50"
    operation["expected_postcondition"]["expected_balance_delta"] = "25.50"
    with pytest.raises(PlanValidationError, match="canonical decimal text"):
        validate_plan(noncanonical)

    fractional = deepcopy(plan)
    fractional.pop("plan_digest")
    fractional["created_at"] = "2026-09-13T10:00:00.1+02:00"
    with pytest.raises(PlanValidationError, match="whole-second precision"):
        validate_plan(fractional)


def test_create_receipt_requires_exact_full_postcondition() -> None:
    plan = write_transactions.build_plan(request())
    operation = plan["operations"][0]
    receipt = {
        "contract_version": 2,
        "plan_id": plan["plan_id"],
        "plan_digest": plan["plan_digest"],
        "classification": "applied",
        "verified": True,
        "operations": [
            {
                "operation_id": operation["operation_id"],
                "status": "applied",
                "transaction_entity": operation["transaction_entity"],
                "transaction_gid": operation["transaction_gid"],
                "durable_numeric_id": "42",
                "durable_uri": ("x-coredata://fixture-store/DepositTransaction/p42"),
                "postcondition": deepcopy(operation["expected_postcondition"]),
            }
        ],
    }
    assert validate_result(plan, receipt) == receipt
    receipt["operations"][0]["postcondition"]["amount"] = "25.49"
    with pytest.raises(PlanValidationError, match="creation postcondition"):
        validate_result(plan, receipt)


def test_retry_safe_creation_receipt_has_no_invented_durable_identity() -> None:
    plan = write_transactions.build_plan(request())
    operation = plan["operations"][0]
    receipt = {
        "contract_version": 2,
        "plan_id": plan["plan_id"],
        "plan_digest": plan["plan_digest"],
        "classification": "retry_safe",
        "verified": False,
        "operations": [
            {
                "operation_id": operation["operation_id"],
                "status": "unknown",
                "transaction_entity": operation["transaction_entity"],
                "transaction_gid": operation["transaction_gid"],
                "durable_numeric_id": None,
                "durable_uri": None,
                "postcondition": None,
            }
        ],
    }
    assert validate_result(plan, receipt) == receipt
    receipt["operations"][0]["durable_numeric_id"] = "42"
    with pytest.raises(PlanValidationError, match="must not claim"):
        validate_result(plan, receipt)


def test_cli_creates_private_immutable_plan_without_reading_db(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request()), encoding="utf-8")
    target = tmp_path / "plans" / "w01.json"
    missing_database = tmp_path / "must-not-be-opened.sqlite"

    arguments = [
        "--db",
        str(missing_database),
        "create",
        "--request",
        str(source),
        "--plan",
        str(target),
    ]
    assert write_transactions.main(arguments) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "planned"
    assert target.stat().st_mode & 0o777 == 0o600
    assert not missing_database.exists()
    assert (
        validate_plan(json.loads(target.read_text()))["plan_digest"]
        == output["plan_digest"]
    )

    assert write_transactions.main(arguments) == 2
    assert (
        "cannot create immutable plan" in json.loads(capsys.readouterr().err)["message"]
    )


def test_writer_client_requires_disposable_capability_only_for_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    monkeypatch.setattr(
        writer_client,
        "require_disposable_write_capability",
        lambda database, capability: calls.append((database, capability)),
    )
    client = WriterClient(
        writer=tmp_path / "writer",
        model=tmp_path / "model",
        store=tmp_path / "fixture.sqlite",
    )
    client._require_operation_capability(write_transactions.build_plan(request()))
    assert calls == [(tmp_path / "fixture.sqlite", "write.create-income")]

    payee_plan = {"capability": "write.reassign-payees-by-id"}
    client._require_operation_capability(payee_plan)
    assert len(calls) == 1
