"""W06 deletion plans stay bound to one observed adjustment and its store."""

from __future__ import annotations

import sys
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import writer_client
from compatibility import CompatibilityError
from test_adjust_balance import request as adjust_request
from write_journal import JournalPaths, JournalStore
from write_plan import PlanValidationError, validate_plan, validate_result
from write_transactions import build_delete_adjustment_plan


def request() -> dict:
    base = adjust_request()
    base["operation"] = {
        "operation_id": "delete-adjustment-1",
        "kind": "delete_investment_total_adjustment",
        "transaction_gid": "existing-adjustment",
        "transaction_numeric_id": "9908",
        "account_gid": base["expected_account_gid"],
        "balance_unit": "investment_total",
        "expected_amount": "-0.75",
        "expected_reconcile_amount": "99.25",
        "expected_prior_balance": "99.25",
        "occurred_at": "2026-09-13T10:00:00+02:00",
        "deletion_reason": "Replace a premature same-session adjustment",
    }
    return base


def receipt(plan: dict, classification: str) -> dict:
    operation = plan["operations"][0]
    return {
        "contract_version": 2,
        "plan_id": plan["plan_id"],
        "plan_digest": plan["plan_digest"],
        "classification": classification,
        "verified": classification in {"applied", "noop"},
        "operations": [{
            "operation_id": operation["operation_id"],
            "status": classification if classification in {"applied", "noop"} else "unknown",
            "transaction_entity": "ReconcileTransaction",
            "transaction_gid": operation["transaction_gid"],
            "durable_numeric_id": operation["transaction_numeric_id"],
            "durable_uri": (
                f"x-coredata://{plan['store_identity']['store_uuid']}/"
                f"ReconcileTransaction/p{operation['transaction_numeric_id']}"
            ),
            "old_payee_gid": None,
            "new_payee_gid": None,
            "postcondition": operation["expected_postcondition"]
            if classification in {"applied", "noop"} else None,
        }],
    }


def test_w06_plan_binds_exact_target_and_preview_balance() -> None:
    plan = build_delete_adjustment_plan(request())
    operation = plan["operations"][0]
    assert operation["transaction_entity"] == "ReconcileTransaction"
    assert operation["transaction_numeric_id"] == "9908"
    assert operation["target_balance"] == "100"
    assert operation["expected_balance_delta"] == "0.75"
    assert operation["expected_postcondition"]["transaction_absent"] is True
    assert validate_plan(plan) == plan


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(currency_unit="EUR"),
    lambda value: value["operation"].update(balance_unit="investment_cash"),
    lambda value: value["operation"].update(transaction_numeric_id="0"),
    lambda value: value["operation"].update(transaction_numeric_id="0009908"),
    lambda value: value["operation"].update(expected_reconcile_amount="99.26"),
    lambda value: value["operation"].update(expected_amount="-0.751"),
    lambda value: value["operation"].update(deletion_reason=""),
])
def test_w06_rejects_unreviewed_request(mutation) -> None:
    candidate = deepcopy(request())
    mutation(candidate)
    with pytest.raises(PlanValidationError):
        build_delete_adjustment_plan(candidate)


def test_w06_receipts_bind_deleted_numeric_identity() -> None:
    plan = build_delete_adjustment_plan(request())
    for classification in ("retry_safe", "unknown", "applied", "noop"):
        assert validate_result(plan, receipt(plan, classification))
    wrong = receipt(plan, "applied")
    wrong["operations"][0]["durable_numeric_id"] = "9909"
    wrong["operations"][0]["durable_uri"] = (
        f"x-coredata://{plan['store_identity']['store_uuid']}/ReconcileTransaction/p9909"
    )
    with pytest.raises(PlanValidationError, match="deleted target"):
        validate_result(plan, wrong)


def test_w06_client_requires_disposable_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = build_delete_adjustment_plan(request())
    checked: list[str] = []

    def reject(_store: Path, capability: str) -> None:
        checked.append(capability)
        raise CompatibilityError("unmarked")

    monkeypatch.setattr(writer_client, "require_disposable_write_capability", reject)
    client = writer_client.WriterClient(Path("host"), Path("model"), Path("store"))
    with pytest.raises(writer_client.WriterClientError, match="unmarked"):
        client._require_operation_capability(plan)
    assert checked == [plan["capability"]]


def test_w06_new_plan_refuses_already_absent_target_before_journal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan = build_delete_adjustment_plan(request())
    store = tmp_path / "disposable.sqlite"
    with sqlite3.connect(store) as connection:
        connection.execute("CREATE TABLE evidence(value TEXT)")
    journal = JournalStore(
        JournalPaths.from_environ({"MONEYWIZ_JOURNAL_DIR": str(tmp_path / "journal")})
    )
    client = writer_client.WriterClient(Path("host"), Path("model"), store)
    monkeypatch.setattr(writer_client, "require_moneywiz_stopped", lambda: None)
    monkeypatch.setattr(client, "_require_operation_capability", lambda _plan: None)

    def inspect(value: dict, *, recover: bool, lock_fd: int) -> dict:
        assert recover is True
        assert lock_fd >= 0
        return receipt(value, "noop")

    monkeypatch.setattr(client, "_invoke", inspect)
    with pytest.raises(writer_client.WriterClientError, match="target to exist"):
        client.apply(plan, plan["plan_digest"], journal)
    assert not list(journal.entries.iterdir())
