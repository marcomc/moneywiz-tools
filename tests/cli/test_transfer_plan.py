"""W07 transfer replacement plans bind both old rows and both account balances."""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from test_transaction_create import request as creation_request
from write_plan import PlanValidationError, validate_plan, validate_result
from write_transactions import build_transfer_plan


def old_row(entity: str, gid: str, numeric_id: str, account: str,
            currency: str, amount: str) -> dict:
    return {
        "transaction_entity": entity,
        "transaction_gid": gid,
        "transaction_numeric_id": numeric_id,
        "account_gid": account,
        "amount": amount,
        "currency_unit": currency,
        "occurred_at": "2026-09-13T09:30:00+02:00",
        "status": 2,
        "flags": 4,
        "reconciled": False,
        "note": "Imported fixture",
        "description": "Synthetic conversion",
        "payee_gid": None,
        "tag_gids": [],
        "category_assignment_uris": [],
    }


def request(*, paired: bool = False, reverse: bool = False) -> dict:
    value = creation_request()
    source_currency, destination_currency = ("EUR", "GBP") if reverse else ("GBP", "EUR")
    source_amount, recipient_amount, rate = ("-23", "20", "0.8695652173913043") if reverse else ("-20", "23", "1.15")
    value["currency_unit"] = source_currency
    value["expected_cached_account_balance"] = "100"
    value["destination_account"] = {
        "account_gid": "account-2",
        "currency_unit": destination_currency,
        "expected_cached_balance": "50",
    }
    value["operation"] = {
        "operation_id": "transfer-1",
        "kind": "replace_import_with_transfer",
        "source_old": old_row("WithdrawTransaction", "import-source", "100",
                              "account-1", source_currency, source_amount),
        "destination_old": (
            old_row("DepositTransaction", "import-recipient", "101", "account-2",
                    destination_currency, recipient_amount) if paired else None
        ),
        "send_at": "2026-09-13T09:30:00+02:00",
        "receive_at": "2026-09-13T09:31:00+02:00",
        "sender_amount": source_amount,
        "recipient_amount": recipient_amount,
        "exchange_rate": rate,
        "fee_amount": "0",
    }
    return value


@pytest.mark.parametrize("paired,reverse", [(False, False), (True, False), (False, True)])
def test_transfer_plan_binds_pair_and_balances(paired: bool, reverse: bool) -> None:
    plan = build_transfer_plan(request(paired=paired, reverse=reverse))
    operation = plan["operations"][0]
    post = operation["expected_postcondition"]
    assert plan["capability"] == "write.replace-import-with-transfer"
    assert post["sender_balance"] == "100"
    assert post["recipient_balance"] == ("50" if paired else "73" if not reverse else "70")
    assert post["old_recipient_numeric_id"] == ("101" if paired else None)
    assert operation["transaction_gid"] != operation["recipient_transaction_gid"]
    assert validate_plan(plan) == plan


@pytest.mark.parametrize("mutation", [
    lambda value: value["operation"].update(fee_amount="0.5"),
    lambda value: value["operation"].update(exchange_rate="1.14"),
    lambda value: value["operation"]["source_old"].update(amount="-21"),
    lambda value: value["operation"]["source_old"].update(status=1),
    lambda value: value["operation"]["source_old"].update(
        transaction_entity="TransferWithdrawTransaction"
    ),
    lambda value: value["destination_account"].update(account_gid="account-1"),
])
def test_transfer_plan_rejects_unreviewed_shape(mutation) -> None:
    value = deepcopy(request())
    mutation(value)
    with pytest.raises(PlanValidationError):
        build_transfer_plan(value)


def test_transfer_receipt_requires_both_new_numeric_ids_and_links() -> None:
    plan = build_transfer_plan(request(paired=True))
    operation = plan["operations"][0]
    prefix = f"x-coredata://{plan['store_identity']['store_uuid']}"
    result = {
        "contract_version": 2,
        "plan_id": plan["plan_id"],
        "plan_digest": plan["plan_digest"],
        "classification": "applied",
        "verified": True,
        "operations": [{
            "operation_id": operation["operation_id"],
            "status": "applied",
            "transaction_entity": "TransferWithdrawTransaction",
            "transaction_gid": operation["transaction_gid"],
            "durable_numeric_id": "200",
            "durable_uri": f"{prefix}/TransferWithdrawTransaction/p200",
            "old_payee_gid": None,
            "new_payee_gid": None,
            "postcondition": operation["expected_postcondition"],
            "transfer_details": {
                "recipient_gid": operation["recipient_transaction_gid"],
                "recipient_numeric_id": "201",
                "recipient_uri": f"{prefix}/TransferDepositTransaction/p201",
                "old_sender_numeric_id": "100",
                "old_recipient_numeric_id": "101",
                "reciprocal_links_verified": True,
            },
        }],
    }
    assert validate_result(plan, result) == result
    result["operations"][0]["transfer_details"]["reciprocal_links_verified"] = False
    with pytest.raises(PlanValidationError, match="W07 receipt pair"):
        validate_result(plan, result)
