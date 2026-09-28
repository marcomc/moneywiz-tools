"""Production-host W02 coverage using a newly constructed model-48 store."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from test_native_transaction_create import (
    W01Runtime,
    _crash,
    _invoke,
    _journal_client,
    _new_store,
    _plan,
)
from test_transaction_create import request
from write_plan import compute_digest, validate_plan, validate_result
from write_transactions import build_edit_plan
from writer_client import WriterClientError

pytest_plugins = ["test_native_transaction_create"]


def _edit_plan(
    runtime: W01Runtime,
    identity: dict[str, str],
    *,
    entity: str = "WithdrawTransaction",
    gid: str = "w02-withdraw",
    changes: dict[str, object] | None = None,
    expected_prior: dict[str, object] | None = None,
    source_event: str = "w02-event",
    expected_balance: str = "0",
    operation_id: str = "operation-w02",
) -> dict:
    payload = request()
    payload.update(
        {
            "plan_id": f"plan-{source_event}",
            "store_identity": {"store_uuid": identity["store_uuid"]},
            "owner_uri": identity["owner_uri"],
            "app_identity": runtime.app_identity,
            "source_event_id": source_event,
            "expected_account_gid": "w01-account",
            "expected_cached_account_balance": expected_balance,
        }
    )
    payload["operation"] = {
        "operation_id": operation_id,
        "kind": "edit_transaction",
        "transaction_entity": entity,
        "transaction_gid": gid,
        "account_gid": "w01-account",
        "changes": changes or {"note": "W02 changed note"},
        "expected_prior": expected_prior or {"note": "W02 original note"},
        "correction_mode": "reject_reconciled",
    }
    return build_edit_plan(payload)


def _inspect(
    runtime: W01Runtime, store: Path, tmp_path: Path, entity: str, gid: str
) -> dict:
    completed = subprocess.run(
        [
            str(runtime.fixture_builder),
            "--inspect",
            "--store",
            str(store),
            "--model",
            str(runtime.model),
            "--entity",
            entity,
            "--gid",
            gid,
        ],
        cwd=tmp_path,
        env=runtime.environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _assert_preserved_except(
    before: dict, after: dict, *, changed_attributes: set[str]
) -> None:
    assert after["entity"] == before["entity"]
    assert after["object_uri"] == before["object_uri"]
    assert after["relationships"] == before["relationships"]
    before_attributes = deepcopy(before["attributes"])
    after_attributes = deepcopy(after["attributes"])
    for key in changed_attributes:
        before_attributes.pop(key)
        after_attributes.pop(key)
    assert after_attributes == before_attributes


def _batch(*plans: dict) -> dict:
    batch = deepcopy(plans[0])
    batch.pop("plan_digest")
    batch["operations"] = [
        deepcopy(operation)
        for plan in plans
        for operation in plan["operations"]
    ]
    return validate_plan(batch)


def _recompute_digest(plan: dict) -> dict:
    malformed = deepcopy(plan)
    malformed.pop("plan_digest")
    malformed["plan_digest"] = compute_digest(malformed)
    return malformed


@pytest.mark.parametrize(
    ("entity", "gid", "old", "new"),
    [
        ("DepositTransaction", "w02-deposit", "10", "12"),
        ("WithdrawTransaction", "w02-withdraw", "-10", "-12"),
        ("RefundTransaction", "w02-refund", "2", "3"),
    ],
)
def test_production_host_edits_amount_and_preserves_identity_and_relationships(
    w01_runtime: W01Runtime,
    tmp_path: Path,
    entity: str,
    gid: str,
    old: str,
    new: str,
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    before = _inspect(w01_runtime, store, tmp_path, entity, gid)
    plan = _edit_plan(
        w01_runtime,
        identity,
        entity=entity,
        gid=gid,
        changes={"amount": new},
        expected_prior={"amount": old},
        source_event=f"amount-{gid}",
    )

    applied = _invoke(w01_runtime, store, plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(plan, json.loads(applied.stdout))["classification"] == (
        "applied"
    )
    after = _inspect(w01_runtime, store, tmp_path, entity, gid)
    assert after["attributes"]["amount"] == pytest.approx(float(new))
    assert after["attributes"]["originalAmount"] == pytest.approx(float(new))
    assert after["account_balance"] == pytest.approx(float(new) - float(old))
    _assert_preserved_except(
        before,
        after,
        changed_attributes={"amount", "originalAmount"},
    )


@pytest.mark.parametrize(
    ("field", "native_field", "old", "new"),
    [
        (
            "occurred_at",
            "date",
            "2026-09-10T11:30:00+02:00",
            "2026-09-11T13:45:00+02:00",
        ),
        ("note", "notes", "W02 original note", None),
        (
            "description",
            "desc",
            "W02 original description",
            "W02 changed description",
        ),
        ("checkbook_number", "checkbookNumber", "W02-001", "W02-002"),
    ],
)
def test_production_host_edits_each_non_amount_scalar(
    w01_runtime: W01Runtime,
    tmp_path: Path,
    field: str,
    native_field: str,
    old: object,
    new: object,
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    before = _inspect(
        w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-withdraw"
    )
    plan = _edit_plan(
        w01_runtime,
        identity,
        changes={field: new},
        expected_prior={field: old},
        source_event=f"scalar-{field}",
    )

    applied = _invoke(w01_runtime, store, plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    receipt = validate_result(plan, json.loads(applied.stdout))
    assert receipt["classification"] == "applied"
    after = _inspect(
        w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-withdraw"
    )
    expected_native = "2026-09-11T11:45:00Z" if field == "occurred_at" else new
    assert after["attributes"][native_field] == expected_native
    assert after["account_balance"] == before["account_balance"]
    _assert_preserved_except(before, after, changed_attributes={native_field})


@pytest.mark.parametrize(
    ("field", "prior", "change"),
    [
        ("amount", "-9", "-12"),
        (
            "occurred_at",
            "2026-09-10T11:31:00+02:00",
            "2026-09-11T13:45:00+02:00",
        ),
        ("note", "stale note", "new note"),
        ("description", "stale description", "new description"),
        ("checkbook_number", "stale number", "W02-002"),
    ],
)
def test_stale_expected_prior_rejects_without_mutation(
    w01_runtime: W01Runtime,
    tmp_path: Path,
    field: str,
    prior: object,
    change: object,
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    before = _inspect(
        w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-withdraw"
    )
    plan = _edit_plan(
        w01_runtime,
        identity,
        changes={field: change},
        expected_prior={field: prior},
        source_event=f"stale-{field}",
    )

    rejected = _invoke(w01_runtime, store, plan, tmp_path)
    assert rejected.returncode == 2
    assert "stale" in rejected.stderr
    assert (
        _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-withdraw")
        == before
    )


@pytest.mark.parametrize(
    "gid",
    [
        "w02-reconciled",
        "w02-flagged",
        "w02-inactive",
        "w02-void",
        "w02-scheduled",
        "w02-fee",
        "w02-investment",
        "w02-fx",
    ],
)
def test_reconciled_and_special_transaction_shapes_fail_closed(
    w01_runtime: W01Runtime, tmp_path: Path, gid: str
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    before = _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", gid)
    plan = _edit_plan(
        w01_runtime,
        identity,
        gid=gid,
        source_event=f"special-{gid}",
    )

    rejected = _invoke(w01_runtime, store, plan, tmp_path)
    assert rejected.returncode == 2
    assert any(
        message in rejected.stderr
        for message in ("ordinary", "reconciled", "unsupported")
    )
    assert _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", gid) == before


def test_category_relationship_allows_text_but_rejects_amount(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    before = _inspect(
        w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-categorized"
    )
    amount = _edit_plan(
        w01_runtime,
        identity,
        gid="w02-categorized",
        changes={"amount": "-5"},
        expected_prior={"amount": "-4"},
        source_event="categorized-amount",
    )
    rejected = _invoke(w01_runtime, store, amount, tmp_path)
    assert rejected.returncode == 2
    assert "category" in rejected.stderr
    assert (
        _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-categorized")
        == before
    )

    text = _edit_plan(
        w01_runtime,
        identity,
        gid="w02-categorized",
        changes={"note": "categorized note"},
        expected_prior={"note": "W02 original note"},
        source_event="categorized-text",
    )
    applied = _invoke(w01_runtime, store, text, tmp_path)
    assert applied.returncode == 0, applied.stderr
    after = _inspect(
        w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-categorized"
    )
    assert after["attributes"]["notes"] == "categorized note"
    _assert_preserved_except(before, after, changed_attributes={"notes"})


@pytest.mark.parametrize(
    ("gid", "old", "new"),
    [
        ("w02-refund", "2", "11"),
        ("w02-refund-original", "-10", "-1"),
    ],
)
def test_refund_graph_invariants_reject_excessive_final_amounts(
    w01_runtime: W01Runtime, tmp_path: Path, gid: str, old: str, new: str
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    entity = "RefundTransaction" if gid == "w02-refund" else "WithdrawTransaction"
    before = _inspect(w01_runtime, store, tmp_path, entity, gid)
    plan = _edit_plan(
        w01_runtime,
        identity,
        entity=entity,
        gid=gid,
        changes={"amount": new},
        expected_prior={"amount": old},
        source_event=f"refund-limit-{gid}",
    )

    rejected = _invoke(w01_runtime, store, plan, tmp_path)
    assert rejected.returncode == 2
    assert "refund" in rejected.stderr
    assert _inspect(w01_runtime, store, tmp_path, entity, gid) == before


def test_edit_preflight_rejects_missing_wrong_entity_owner_account_and_balance(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    cases = [
        ({"gid": "missing-transaction"}, "expected one"),
        ({"entity": "DepositTransaction"}, "expected one"),
        ({"expected_balance": "1"}, "stale"),
    ]
    for index, (overrides, message) in enumerate(cases):
        plan = _edit_plan(
            w01_runtime,
            identity,
            source_event=f"wrong-reference-{index}",
            **overrides,
        )
        rejected = _invoke(w01_runtime, store, plan, tmp_path)
        assert rejected.returncode == 2
        assert message in rejected.stderr

    wrong_owner = _edit_plan(w01_runtime, identity, source_event="wrong-owner")
    wrong_owner.pop("plan_digest")
    wrong_owner["owner_uri"] = "x-coredata://wrong/User/p999"
    wrong_owner["operations"][0]["owner_uri"] = wrong_owner["owner_uri"]
    wrong_owner = validate_plan(wrong_owner)
    rejected_owner = _invoke(w01_runtime, store, wrong_owner, tmp_path)
    assert rejected_owner.returncode == 2
    assert "owner" in rejected_owner.stderr

    wrong_account = _edit_plan(w01_runtime, identity, source_event="wrong-account")
    wrong_account.pop("plan_digest")
    wrong_account["expected_account_gid"] = "w01-other-account"
    wrong_account["operations"][0]["account_gid"] = "w01-other-account"
    wrong_account = validate_plan(wrong_account)
    rejected_account = _invoke(w01_runtime, store, wrong_account, tmp_path)
    assert rejected_account.returncode == 2
    assert "account" in rejected_account.stderr.lower()


def test_batch_preflight_rolls_back_all_edits_atomically(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    before = _inspect(
        w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-withdraw"
    )
    first = _edit_plan(
        w01_runtime,
        identity,
        changes={"note": "must roll back"},
        expected_prior={"note": "W02 original note"},
        source_event="atomic-batch",
        operation_id="operation-first",
    )
    second = _edit_plan(
        w01_runtime,
        identity,
        entity="DepositTransaction",
        gid="w02-deposit",
        changes={"description": "must reject"},
        expected_prior={"description": "stale description"},
        source_event="atomic-batch",
        operation_id="operation-second",
    )
    batch = deepcopy(first)
    batch.pop("plan_digest")
    batch["operations"].append(second["operations"][0])
    batch = validate_plan(batch)

    rejected = _invoke(w01_runtime, store, batch, tmp_path)
    assert rejected.returncode == 2
    assert "stale" in rejected.stderr
    assert (
        _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-withdraw")
        == before
    )


def test_applied_edit_repeats_and_recovers_as_noop(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _edit_plan(w01_runtime, identity, source_event="repeat")

    applied = _invoke(w01_runtime, store, plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(plan, json.loads(applied.stdout))["classification"] == (
        "applied"
    )
    for repeated in (
        _invoke(w01_runtime, store, plan, tmp_path),
        _invoke(w01_runtime, store, plan, tmp_path, recover=True),
    ):
        assert repeated.returncode == 0, repeated.stderr
        assert validate_result(plan, json.loads(repeated.stdout))["classification"] == (
            "noop"
        )


def test_recovery_before_edit_is_retry_safe(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _edit_plan(w01_runtime, identity, source_event="recovery-before-edit")

    recovered = _invoke(w01_runtime, store, plan, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    receipt = validate_result(plan, json.loads(recovered.stdout))
    assert receipt["classification"] == "retry_safe"
    assert receipt["operations"][0]["durable_uri"]
    assert receipt["operations"][0]["durable_numeric_id"]


@pytest.mark.parametrize(
    ("crash_flag", "expected_exit", "classification"),
    [
        ("--crash-before-save", 86, "retry_safe"),
        ("--crash-after-save", 87, "noop"),
    ],
)
def test_w02_crash_boundary_is_classified_by_production_recovery(
    w01_runtime: W01Runtime,
    tmp_path: Path,
    crash_flag: str,
    expected_exit: int,
    classification: str,
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _edit_plan(
        w01_runtime,
        identity,
        source_event=f"{crash_flag.removeprefix('--')}-edit",
    )
    crashed = _crash(w01_runtime, store, plan, tmp_path, crash_flag)
    assert crashed.returncode == expected_exit, crashed.stderr

    recovered = _invoke(w01_runtime, store, plan, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(plan, json.loads(recovered.stdout))["classification"] == (
        classification
    )


@pytest.mark.parametrize(
    ("kind", "amount"),
    [
        ("create_income", "2"),
        ("create_expense", "-2"),
        ("create_refund", "2"),
    ],
)
def test_w01_created_transaction_can_be_edited_by_w02(
    w01_runtime: W01Runtime, tmp_path: Path, kind: str, amount: str
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    creation = _plan(
        w01_runtime,
        identity,
        kind=kind,
        amount=amount,
        source_event=f"create-then-edit-{kind}",
    )
    created = _invoke(w01_runtime, store, creation, tmp_path)
    assert created.returncode == 0, created.stderr
    assert validate_result(creation, json.loads(created.stdout))["classification"] == (
        "applied"
    )
    created_operation = creation["operations"][0]
    entity = created_operation["transaction_entity"]
    gid = created_operation["transaction_gid"]
    before = _inspect(w01_runtime, store, tmp_path, entity, gid)
    edit = _edit_plan(
        w01_runtime,
        identity,
        entity=entity,
        gid=gid,
        changes={"note": f"W02 edited {kind}"},
        expected_prior={"note": "Synthetic W01 fixture"},
        expected_balance=amount,
        source_event=f"edit-created-{kind}",
    )

    edited = _invoke(w01_runtime, store, edit, tmp_path)
    assert edited.returncode == 0, edited.stderr
    assert validate_result(edit, json.loads(edited.stdout))["classification"] == (
        "applied"
    )
    after = _inspect(w01_runtime, store, tmp_path, entity, gid)
    assert after["attributes"]["notes"] == f"W02 edited {kind}"
    assert after["account_balance"] == pytest.approx(float(amount))
    _assert_preserved_except(before, after, changed_attributes={"notes"})


def test_positive_refund_batch_validates_combined_final_graph(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    original = _edit_plan(
        w01_runtime,
        identity,
        gid="w02-refund-original",
        changes={"amount": "-9"},
        expected_prior={"amount": "-10"},
        source_event="refund-batch",
        operation_id="edit-refund-original",
    )
    refund = _edit_plan(
        w01_runtime,
        identity,
        entity="RefundTransaction",
        gid="w02-refund",
        changes={"amount": "4"},
        expected_prior={"amount": "2"},
        source_event="refund-batch",
        operation_id="edit-refund",
    )
    batch = _batch(original, refund)

    applied = _invoke(w01_runtime, store, batch, tmp_path)
    assert applied.returncode == 0, applied.stderr
    receipt = validate_result(batch, json.loads(applied.stdout))
    assert receipt["classification"] == "applied"
    assert len(receipt["operations"]) == 2
    original_after = _inspect(
        w01_runtime,
        store,
        tmp_path,
        "WithdrawTransaction",
        "w02-refund-original",
    )
    refund_after = _inspect(
        w01_runtime, store, tmp_path, "RefundTransaction", "w02-refund"
    )
    assert original_after["attributes"]["amount"] == pytest.approx(-9)
    assert refund_after["attributes"]["amount"] == pytest.approx(4)
    assert original_after["account_balance"] == pytest.approx(3)
    assert refund_after["account_balance"] == pytest.approx(3)


def test_two_refund_cumulative_limit_rejects_second_refund_edit(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    first_before = _inspect(
        w01_runtime, store, tmp_path, "RefundTransaction", "w02-refund"
    )
    second_before = _inspect(
        w01_runtime, store, tmp_path, "RefundTransaction", "w02-refund-second"
    )
    excessive = _edit_plan(
        w01_runtime,
        identity,
        entity="RefundTransaction",
        gid="w02-refund-second",
        changes={"amount": "9"},
        expected_prior={"amount": "3"},
        source_event="two-refund-limit",
    )

    rejected = _invoke(w01_runtime, store, excessive, tmp_path)
    assert rejected.returncode == 2
    assert "refund total exceeds" in rejected.stderr
    assert (
        _inspect(w01_runtime, store, tmp_path, "RefundTransaction", "w02-refund")
        == first_before
    )
    assert (
        _inspect(
            w01_runtime,
            store,
            tmp_path,
            "RefundTransaction",
            "w02-refund-second",
        )
        == second_before
    )


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        ("allowlist", "W02 edit contains"),
        ("unknown_field", "W02 edit contains"),
        ("correction_mode", "W02 edit contains"),
        ("special_entity", "W02 edit contains"),
    ],
)
def test_native_independently_rejects_malformed_edit_contract(
    w01_runtime: W01Runtime, tmp_path: Path, damage: str, message: str
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    before = _inspect(
        w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-withdraw"
    )
    plan = _edit_plan(
        w01_runtime, identity, source_event=f"native-contract-{damage}"
    )
    operation = plan["operations"][0]
    if damage == "allowlist":
        operation["allowed_changed_fields"] = ["notes", "payee"]
    elif damage == "unknown_field":
        operation["unreviewed_field"] = "surprise"
    elif damage == "correction_mode":
        operation["correction_mode"] = "allow_reconciled"
    else:
        operation["transaction_entity"] = "TransferTransaction"
    malformed = _recompute_digest(plan)

    rejected = _invoke(w01_runtime, store, malformed, tmp_path)
    assert rejected.returncode == 2
    assert message in rejected.stderr
    assert (
        _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-withdraw")
        == before
    )


def test_writer_client_applies_and_repeats_edit_with_verified_journal(
    w01_runtime: W01Runtime,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _edit_plan(w01_runtime, identity, source_event="journal-edit-repeat")
    client, journal = _journal_client(w01_runtime, store, tmp_path, monkeypatch)

    applied = client.apply(plan, plan["plan_digest"], journal)
    assert applied["classification"] == "applied"
    assert applied["verified"] is True
    assert journal.load(plan["plan_id"])["state"] == "verified"

    repeated = client.apply(plan, plan["plan_digest"], journal)
    assert repeated["classification"] == "noop"
    assert repeated["verified"] is True
    assert journal.load(plan["plan_id"])["state"] == "verified"


@pytest.mark.parametrize(
    ("crash_point", "recovery_classification"),
    [("before-save", "retry_safe"), ("after-save", "noop")],
)
def test_writer_client_recovers_prepared_edit_journal_after_crash(
    w01_runtime: W01Runtime,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_point: str,
    recovery_classification: str,
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _edit_plan(
        w01_runtime, identity, source_event=f"journal-edit-{crash_point}"
    )
    client, journal = _journal_client(w01_runtime, store, tmp_path, monkeypatch)
    monkeypatch.setenv("MONEYWIZ_TEST_CRASH_POINT", crash_point)

    with pytest.raises(WriterClientError, match="unknown"):
        client.apply(plan, plan["plan_digest"], journal)
    assert journal.load(plan["plan_id"])["state"] == "unresolved"

    monkeypatch.delenv("MONEYWIZ_TEST_CRASH_POINT")
    recovered = client.recover(plan, journal)
    assert recovered["classification"] == recovery_classification
    if crash_point == "before-save":
        assert journal.load(plan["plan_id"])["state"] == "unresolved"
        applied = client.apply(plan, plan["plan_digest"], journal)
        assert applied["classification"] == "applied"
    assert journal.load(plan["plan_id"])["state"] == "verified"


def test_writer_client_refuses_replay_after_verified_edit_drift(
    w01_runtime: W01Runtime,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _edit_plan(w01_runtime, identity, source_event="journal-verified-drift")
    client, journal = _journal_client(w01_runtime, store, tmp_path, monkeypatch)
    applied = client.apply(plan, plan["plan_digest"], journal)
    assert applied["classification"] == "applied"

    drift = _edit_plan(
        w01_runtime,
        identity,
        changes={"note": "W02 drifted note"},
        expected_prior={"note": "W02 changed note"},
        source_event="external-edit-drift",
    )
    drifted = _invoke(w01_runtime, store, drift, tmp_path)
    assert drifted.returncode == 0, drifted.stderr

    recovered = client.recover(plan, journal)
    assert recovered["classification"] == "unknown"
    assert recovered["verified"] is False
    assert journal.load(plan["plan_id"])["ever_verified"] is True
    with pytest.raises(WriterClientError, match="refusing replay"):
        client.apply(plan, plan["plan_digest"], journal)


def test_unmarked_store_cannot_enter_edit_handler(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path, marked=False)
    plan = _edit_plan(w01_runtime, identity, source_event="unmarked-edit")
    rejected = _invoke(w01_runtime, store, plan, tmp_path)
    assert rejected.returncode == 2
    assert "marked disposable fixture required" in rejected.stderr


def test_direct_host_rejects_marked_store_without_fixture_identity(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    before = _inspect(
        w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-withdraw"
    )
    with sqlite3.connect(store) as connection:
        connection.execute(
            "UPDATE ZUSER SET ZSYNCLOGIN=? WHERE ZSYNCLOGIN=?",
            ("different-owner@example.invalid", "w01-fixture@example.invalid"),
        )
    plan = _edit_plan(w01_runtime, identity, source_event="marked-other-owner")

    rejected = _invoke(w01_runtime, store, plan, tmp_path)
    assert rejected.returncode == 2
    assert "disposable CashAccount" in rejected.stderr
    assert (
        _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-withdraw")
        == before
    )
