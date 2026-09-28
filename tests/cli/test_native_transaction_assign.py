"""W03 native replacement on newly invented disposable model-48 stores."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from test_native_transaction_create import W01Runtime, _crash, _invoke, _new_store
from test_native_transaction_edit import _inspect
from test_transaction_assign import request
from write_plan import compute_digest, validate_plan, validate_result
from write_transactions import build_assign_plan

pytest_plugins = ["test_native_transaction_create"]


def _plan(runtime: W01Runtime, identity: dict[str, str], *, gid="w02-categorized",
          amount="-4", category="w01-category") -> dict:
    payload = request()
    payload.update({
        "store_identity": {"store_uuid": identity["store_uuid"]},
        "owner_uri": identity["owner_uri"],
        "app_identity": runtime.app_identity,
        "expected_account_gid": "w01-account",
        "expected_cached_account_balance": "0",
    })
    payload["operation"].update(transaction_gid=gid, amount=amount)
    payload["operation"]["account_gid"] = "w01-account"
    payload["operation"]["expected_assignments"]["category_splits"] = (
        [{"category_gid": category, "amount": amount}] if category else []
    )
    payload["operation"]["target"]["category_splits"] = [
        {"category_gid": "w03-category", "amount": amount}
    ]
    return build_assign_plan(payload)


def test_replaces_payee_and_category_and_recovers_noop(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    before = _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-categorized")
    plan = _plan(w01_runtime, identity)
    applied = _invoke(w01_runtime, store, plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(plan, json.loads(applied.stdout))["classification"] == "applied"
    after = _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-categorized")
    assert after["object_uri"] == before["object_uri"]
    assert after["attributes"] == before["attributes"]
    assert after["account_balance"] == before["account_balance"]
    assert after["relationships"]["payee"] != before["relationships"]["payee"]
    assert after["relationships"]["categoriesAssigments"] != before["relationships"]["categoriesAssigments"]
    for key in before["relationships"].keys() - {"payee", "categoriesAssigments"}:
        assert after["relationships"][key] == before["relationships"][key]
    repeated = _invoke(w01_runtime, store, plan, tmp_path)
    assert repeated.returncode == 0, repeated.stderr
    assert validate_result(plan, json.loads(repeated.stdout))["classification"] == "noop"


@pytest.mark.parametrize("mode", ["add_splits", "remove_splits", "payee_only", "category_only"])
def test_explicit_add_remove_or_payee_only_replacement(
    w01_runtime: W01Runtime, tmp_path: Path, mode: str
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    if mode == "add_splits":
        gid, amount, category = "w02-withdraw", "-10", ""
    else:
        gid, amount, category = "w02-categorized", "-4", "w01-category"
    plan = _plan(w01_runtime, identity, gid=gid, amount=amount, category=category)
    target = plan["operations"][0]["target"]
    if mode == "remove_splits":
        target["category_splits"] = []
    elif mode == "payee_only":
        target["category_splits"] = deepcopy(
            plan["operations"][0]["expected_assignments"]["category_splits"]
        )
    elif mode == "category_only":
        target["payee_gid"] = "w01-payee"
    plan["operations"][0]["expected_postcondition"] = {
        **deepcopy(target), "expected_balance_delta": "0",
    }
    plan["plan_digest"] = compute_digest(plan)
    validate_plan(plan)
    before = _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", gid)
    applied = _invoke(w01_runtime, store, plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(plan, json.loads(applied.stdout))["classification"] == "applied"
    after = _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", gid)
    assert after["account_balance"] == before["account_balance"]
    assert len(after["relationships"]["categoriesAssigments"]) == len(target["category_splits"])
    if mode == "payee_only":
        assert after["relationships"]["categoriesAssigments"] == before["relationships"]["categoriesAssigments"]
    if mode == "category_only":
        assert after["relationships"]["payee"] == before["relationships"]["payee"]


@pytest.mark.parametrize("mutation", ["stale_payee", "foreign_payee", "foreign_category", "wrong_amount", "reconciled"])
def test_rejects_stale_foreign_or_unsupported_without_mutation(
    w01_runtime: W01Runtime, tmp_path: Path, mutation: str
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, identity)
    if mutation == "stale_payee":
        plan["operations"][0]["expected_assignments"]["payee_gid"] = "w03-payee"
    elif mutation == "foreign_payee":
        plan["operations"][0]["target"]["payee_gid"] = "w01-foreign-payee"
        plan["operations"][0]["expected_postcondition"]["payee_gid"] = "w01-foreign-payee"
    elif mutation == "foreign_category":
        split = [{"category_gid": "w01-foreign-category", "amount": "-4"}]
        plan["operations"][0]["target"]["category_splits"] = deepcopy(split)
        plan["operations"][0]["expected_postcondition"]["category_splits"] = deepcopy(split)
    elif mutation == "wrong_amount":
        plan["operations"][0]["amount"] = "-5"
    else:
        plan["operations"][0]["transaction_gid"] = "w02-reconciled"
        plan["operations"][0]["amount"] = "-3"
        plan["operations"][0]["expected_assignments"]["category_splits"] = []
    from write_plan import compute_digest
    plan["plan_digest"] = compute_digest(plan)
    before = _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-categorized")
    rejected = _invoke(w01_runtime, store, plan, tmp_path)
    assert rejected.returncode != 0
    assert _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-categorized") == before


def test_multi_transaction_failure_rolls_back_entire_assignment_unit(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    first = _plan(w01_runtime, identity)
    second = _plan(w01_runtime, identity, gid="w02-withdraw", amount="-10", category="")
    second_operation = second["operations"][0]
    second_operation["operation_id"] = "assign-2"
    second_operation["target"]["category_splits"] = [
        {"category_gid": "w01-foreign-category", "amount": "-10"}
    ]
    second_operation["expected_postcondition"]["category_splits"] = deepcopy(
        second_operation["target"]["category_splits"]
    )
    batch = deepcopy(first)
    batch["operations"].append(second_operation)
    batch["plan_digest"] = compute_digest(batch)
    validate_plan(batch)
    before = _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-categorized")
    rejected = _invoke(w01_runtime, store, batch, tmp_path)
    assert rejected.returncode != 0
    assert _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-categorized") == before


@pytest.mark.parametrize(("crash_point", "expected"), [("before", "retry_safe"), ("after", "noop")])
def test_crash_recovery_classifies_exact_assignment_state(
    w01_runtime: W01Runtime, tmp_path: Path, crash_point: str, expected: str
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, identity)
    crashed = _crash(w01_runtime, store, plan, tmp_path, f"--crash-{crash_point}-save")
    assert crashed.returncode in {86, 87}, crashed.stderr
    recovered = _invoke(w01_runtime, store, plan, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(plan, json.loads(recovered.stdout))["classification"] == expected
