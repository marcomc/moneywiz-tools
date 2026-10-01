"""Account subtype coverage and native ledger behavior on invented stores."""

import json
from dataclasses import replace

import pytest

from test_native_transaction_create import (
    ACCOUNT_ENTITIES, _invoke, _new_store, _plan, w01_runtime,
)
from test_native_transaction_edit import _edit_plan, _inspect
from test_native_transaction_assign import _plan as assignment_plan
from test_native_transaction_reconcile import _plan as reconciliation_plan
from test_native_transfer import _fixture, _plan as transfer_plan
from write_plan import validate_plan, validate_result

__all__ = ["w01_runtime"]


@pytest.mark.parametrize("entity", ACCOUNT_ENTITIES)
def test_edit_assign_and_reconcile_preserve_account_subtype(w01_runtime, tmp_path, entity):
    store, identity = _new_store(w01_runtime, tmp_path, account_entity=entity)
    before = _inspect(w01_runtime, store, tmp_path, entity, "w01-account")
    plans = (
        _edit_plan(w01_runtime, identity),
        assignment_plan(w01_runtime, identity),
        reconciliation_plan(w01_runtime, identity),
    )
    for plan in plans:
        applied = _invoke(w01_runtime, store, plan, tmp_path)
        assert applied.returncode == 0, applied.stderr
        assert validate_result(plan, json.loads(applied.stdout))["classification"] == "applied"
        replay = _invoke(w01_runtime, store, plan, tmp_path)
        assert replay.returncode == 0, replay.stderr
        assert validate_result(plan, json.loads(replay.stdout))["classification"] == "noop"
    assert _inspect(w01_runtime, store, tmp_path, entity, "w01-account") == before


@pytest.mark.parametrize("entity", ACCOUNT_ENTITIES)
def test_transfer_accepts_every_account_subtype(w01_runtime, tmp_path, entity):
    runtime = replace(w01_runtime, environment={
        **w01_runtime.environment, "MONEYWIZ_TEST_ACCOUNT_ENTITY": entity,
    })
    store, identity = _fixture(runtime, tmp_path, "--w07-paired")
    plan = transfer_plan(runtime, tmp_path, identity, paired=True)
    before = _inspect(runtime, store, tmp_path, entity, "w07-source")["attributes"]
    applied = _invoke(runtime, store, plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(plan, json.loads(applied.stdout))["classification"] == "applied"
    assert _inspect(runtime, store, tmp_path, entity, "w07-source")["attributes"] == before


def test_fixture_shape_uses_cache_delta_and_reporting_rate(w01_runtime, tmp_path):
    runtime = w01_runtime
    store, identity = _new_store(runtime, tmp_path, account_entity="BankChequeAccount")
    plan = _plan(runtime, identity)
    plan.pop("plan_digest")
    operation = plan["operations"][0]
    fields = {"description": "TEST native account", "reporting_exchange_rate": "0.752775"}
    operation["category_splits"] = []
    operation["expected_postcondition"]["category_splits"] = []
    operation.update(fields)
    operation["expected_postcondition"].update(fields)
    plan = validate_plan(plan)
    applied = _invoke(runtime, store, plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(plan, json.loads(applied.stdout))["classification"] == "applied"
    row = _inspect(runtime, store, tmp_path, "DepositTransaction", operation["transaction_gid"])
    assert row["account_balance"] == 2
    assert row["attributes"]["status"] == 1
    assert row["attributes"]["desc"] == fields["description"]
    assert row["attributes"]["currencyExchangeRate"] == 0.752775
    replay = _invoke(runtime, store, plan, tmp_path)
    assert replay.returncode == 0, replay.stderr
    assert validate_result(plan, json.loads(replay.stdout))["classification"] == "noop"
    edit = _edit_plan(runtime, identity, expected_balance="2")
    edit.pop("plan_digest")
    edit_operation = edit["operations"][0]
    edit_operation.update(transaction_entity="DepositTransaction", transaction_gid=operation["transaction_gid"])
    edit_operation["changes"] = {"amount": "3"}
    edit_operation["expected_prior"] = {"amount": "2"}
    edit_operation["expected_balance_delta"] = "1"
    edit_operation["allowed_changed_fields"] = ["amount", "originalAmount"]
    edit_operation["expected_postcondition"] = {
        "fields": {"amount": "3"}, "expected_balance_delta": "1",
    }
    edit = validate_plan(edit)
    changed = _invoke(runtime, store, edit, tmp_path)
    assert changed.returncode == 0, changed.stderr
    after = _inspect(runtime, store, tmp_path, "DepositTransaction", operation["transaction_gid"])
    assert after["account_balance"] == 3
    assert after["attributes"]["amount"] == 3
    assert after["attributes"]["currencyExchangeRate"] == 0.752775


def test_unmarked_store_requires_disposable_marker(w01_runtime, tmp_path):
    store, identity = _new_store(w01_runtime, tmp_path, marked=False)
    plan = _plan(w01_runtime, identity)
    refused = _invoke(w01_runtime, store, plan, tmp_path)
    assert refused.returncode == 2
    assert "marked disposable fixture required" in refused.stderr
