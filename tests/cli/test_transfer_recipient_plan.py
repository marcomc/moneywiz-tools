"""W10 plans bind and preserve both linked transfer legs."""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from test_transaction_create import request as creation_request
from write_plan import PlanValidationError, validate_plan
from write_transactions import build_transfer_recipient_plan


def _leg(entity: str, gid: str, numeric_id: str, account: str, peer_account: str,
         amount: str, peer_amount: str, occurred_at: str, peer_gid: str) -> dict:
    return {
        "transaction_entity": entity,
        "transaction_gid": gid,
        "transaction_numeric_id": numeric_id,
        "account_gid": account,
        "amount": amount,
        "currency_unit": "GBP",
        "occurred_at": occurred_at,
        "status": 2,
        "flags": 0,
        "reconciled": False,
        "note": "",
        "description": "Transfer",
        "fee": "0",
        "original_fee": "0",
        "original_fee_currency": None,
        "original_amount": amount,
        "peer_amount": peer_amount,
        "peer_currency_unit": "GBP",
        "exchange_rate": "1",
        "peer_transaction_gid": peer_gid,
        "peer_account_gid": peer_account,
        "payee_gid": None,
        "tag_gids": [],
        "category_assignment_uris": [],
    }


def request() -> dict:
    value = creation_request()
    value["currency_unit"] = "GBP"
    value["expected_account_gid"] = "account-source"
    value["expected_cached_account_balance"] = "1200"
    value["previous_destination_account"] = {
        "account_gid": "account-old",
        "currency_unit": "GBP",
        "expected_cached_balance": "100",
    }
    value["destination_account"] = {
        "account_gid": "account-new",
        "currency_unit": "GBP",
        "expected_cached_balance": "250",
    }
    value["operation"] = {
        "operation_id": "recipient-edit-1",
        "kind": "reassign_transfer_recipient",
        "expected_pair": {
            "sender": _leg("TransferWithdrawTransaction", "sender-gid", "101",
                            "account-source", "account-old", "-300", "300",
                            "2026-09-28T12:06:00+02:00", "recipient-gid"),
            "recipient": _leg("TransferDepositTransaction", "recipient-gid", "102",
                               "account-old", "account-source", "300", "-300",
                               "2026-09-28T12:07:00+02:00", "sender-gid"),
        },
    }
    return value


def test_transfer_recipient_plan_binds_existing_pair_and_accounts() -> None:
    plan = build_transfer_recipient_plan(request())
    operation = plan["operations"][0]

    assert plan["capability"] == "write.reassign-transfer-recipient"
    assert operation["transaction_gid"] == "sender-gid"
    assert operation["recipient_transaction_gid"] == "recipient-gid"
    assert operation["expected_postcondition"] == {
        "sender_gid": "sender-gid",
        "recipient_gid": "recipient-gid",
        "sender_account_gid": "account-source",
        "previous_destination_account_gid": "account-old",
        "destination_account_gid": "account-new",
        "recipient_amount": "300",
        "receive_at": "2026-09-28T12:07:00+02:00",
    }
    assert validate_plan(plan) == plan


@pytest.mark.parametrize("mutation", [
    lambda value: value["destination_account"].update(currency_unit="EUR"),
    lambda value: value["destination_account"].update(account_gid="account-source"),
    lambda value: value["operation"]["expected_pair"]["sender"].update(flags=True),
    lambda value: value["operation"]["expected_pair"]["recipient"].update(peer_transaction_gid="other"),
    lambda value: value["operation"]["expected_pair"]["recipient"].update(amount="-300"),
    lambda value: value["operation"]["expected_pair"]["sender"].update(note=" changed "),
])
def test_transfer_recipient_plan_rejects_stale_or_unsafe_pair(mutation) -> None:
    value = deepcopy(request())
    mutation(value)
    with pytest.raises(PlanValidationError):
        build_transfer_recipient_plan(value)
