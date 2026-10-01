"""Native W05 creation, independent read-back and recovery on invented stores."""

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from test_extended_adjust_balance import request
from test_investment_plan import request as investment_request
from test_native_transaction_create import _invoke, w01_runtime
from test_native_transaction_edit import _inspect
from write_plan import compute_digest, validate_result
from write_transactions import _ENVELOPE_FIELDS, build_adjust_balance_plan, build_investment_plan

__all__ = ["w01_runtime"]


def fixture(runtime, tmp_path, kind, *, marked=True, entity=None, currency="EUR"):
    variant = {"adjust_account_balance": "balance", "adjust_investment_cash": "cash",
               "adjust_asset_quantity": "quantity"}[kind]
    environment = {**runtime.environment, "MONEYWIZ_TEST_CURRENCY": currency}
    if entity:
        environment["MONEYWIZ_TEST_ACCOUNT_ENTITY"] = entity
    runtime = replace(runtime, environment=environment)
    store = tmp_path / "w05-disposable.sqlite"
    mode = f"--w05-{'unmarked-' if not marked else ''}{variant}"
    built = subprocess.run([str(runtime.fixture_builder), "--store", str(store),
                            "--model", str(runtime.model), mode],
                           env=environment, capture_output=True, text=True, check=False)
    assert built.returncode == 0, built.stderr
    identity = json.loads(built.stdout)
    payload = request(kind, currency)
    payload.update(store_identity={"store_uuid": identity["store_uuid"]},
                   owner_uri=identity["owner_uri"], app_identity=runtime.app_identity,
                   expected_account_gid="w05-account", timezone="UTC")
    payload["operation"].update(account_gid="w05-account", occurred_at="2026-09-13T10:00:00Z")
    if kind == "adjust_asset_quantity" and entity == "InvestmentAccount":
        payload["operation"]["asset_type"] = 0
    return runtime, store, build_adjust_balance_plan(payload)


@pytest.mark.parametrize("currency", ["GBP", "EUR", "USD", "CAD"])
@pytest.mark.parametrize("entity", ["CashAccount", "BankChequeAccount", "BankSavingAccount",
                                   "CreditCardAccount", "LoanAccount"])
def test_w05_native_ordinary_subtypes_and_currencies(w01_runtime, tmp_path, entity, currency):
    runtime, store, plan = fixture(w01_runtime, tmp_path, "adjust_account_balance", entity=entity, currency=currency)
    before = _inspect(runtime, store, tmp_path, entity, "w05-account")
    applied = _invoke(runtime, store, plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(plan, json.loads(applied.stdout))["classification"] == "applied"
    operation = plan["operations"][0]
    row = _inspect(runtime, store, tmp_path, "ReconcileTransaction", operation["transaction_gid"])
    assert row["attributes"]["amount"] == 0.01
    assert row["attributes"]["reconcileAmount"] == 100.01
    assert row["attributes"]["originalAmount"] == 0
    assert row["attributes"]["currencyExchangeRate"] == 1
    assert row["attributes"]["desc"] == "TEST W05 balance"
    assert _inspect(runtime, store, tmp_path, entity, "w05-account")["attributes"] == before["attributes"]
    replay = _invoke(runtime, store, plan, tmp_path, recover=True)
    assert replay.returncode == 0, replay.stderr
    assert validate_result(plan, json.loads(replay.stdout))["classification"] == "noop"


@pytest.mark.parametrize("entity", ["InvestmentAccount", "ForexAccount"])
@pytest.mark.parametrize("target,delta", [("1.01499999", "-0.00000001"), ("1.01500001", "0.00000001")])
def test_w05_existing_stock_and_forex_quantity(w01_runtime, tmp_path, entity, target, delta):
    runtime, store, plan = fixture(w01_runtime, tmp_path, "adjust_asset_quantity", entity=entity)
    operation = plan["operations"][0]
    operation.update(target_balance=target, expected_balance_delta=delta)
    operation["expected_postcondition"].update(target_balance=target, expected_balance_delta=delta)
    plan["plan_digest"] = compute_digest(plan)
    before = _inspect(runtime, store, tmp_path, "InvestmentHolding", "w05-holding")
    applied = _invoke(runtime, store, plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(plan, json.loads(applied.stdout))["classification"] == "applied"
    row = _inspect(runtime, store, tmp_path, "ReconcileTransaction", operation["transaction_gid"])
    assert row["attributes"]["amount"] == 0
    assert row["attributes"]["numberOfShares"] == float(delta)
    assert row["attributes"]["reconcileNumberOfShares"] == float(target)
    assert _inspect(runtime, store, tmp_path, "InvestmentHolding", "w05-holding")["attributes"] == before["attributes"]
    recovered = _invoke(runtime, store, plan, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(plan, json.loads(recovered.stdout))["classification"] == "noop"


@pytest.mark.parametrize("kind", ["investment_buy", "investment_sell"])
def test_w05_stock_quantity_adjustment_then_buy_or_sell(w01_runtime, tmp_path, kind):
    runtime, store, adjustment = fixture(w01_runtime, tmp_path, "adjust_asset_quantity", entity="InvestmentAccount")
    applied = _invoke(runtime, store, adjustment, tmp_path)
    assert applied.returncode == 0, applied.stderr
    payload = investment_request(kind)
    payload.update(store_identity=adjustment["store_identity"], owner_uri=adjustment["owner_uri"],
                   app_identity=runtime.app_identity, expected_account_gid="w05-account",
                   currency_unit="EUR", timezone="UTC", source_event_id=f"w05-followup-{kind}")
    payload["operation"].update(account_gid="w05-account", payee_gid=None, tag_gids=[],
                                holding_gid="w05-holding", holding_symbol="ETH", asset_type=0,
                                occurred_at="2026-09-14T10:00:00Z", expected_prior_cash="100",
                                expected_prior_units="1.01500001", quantity="0.01", unit_price="5",
                                fee="0.01", amount="-0.06" if kind == "investment_buy" else "0.04")
    trade = build_investment_plan(payload)
    result = _invoke(runtime, store, trade, tmp_path)
    assert result.returncode == 0, result.stderr
    assert validate_result(trade, json.loads(result.stdout))["classification"] == "applied"
    replay = _invoke(runtime, store, trade, tmp_path, recover=True)
    assert replay.returncode == 0, replay.stderr
    assert validate_result(trade, json.loads(replay.stdout))["classification"] == "noop"


@pytest.mark.parametrize("kind", ["adjust_account_balance", "adjust_investment_cash", "adjust_asset_quantity"])
def test_w05_matching_target_noop_creates_no_row(w01_runtime, tmp_path, kind):
    runtime, store, plan = fixture(w01_runtime, tmp_path, kind)
    operation = plan["operations"][0]
    operation.update(target_balance=operation["expected_prior_balance"], expected_balance_delta="0")
    operation["expected_postcondition"].update(target_balance=operation["target_balance"], expected_balance_delta="0")
    plan["plan_digest"] = compute_digest(plan)
    for recover in [False, True]:
        result = _invoke(runtime, store, plan, tmp_path, recover=recover)
        assert result.returncode == 0, result.stderr
        receipt = validate_result(plan, json.loads(result.stdout))
        assert receipt["classification"] == "noop"
        assert receipt["operations"][0]["durable_uri"] is None


@pytest.mark.parametrize("kind", ["adjust_investment_cash", "adjust_asset_quantity"])
@pytest.mark.parametrize("currency", ["GBP", "EUR", "USD", "CAD"])
def test_w05_native_investment_cash_and_quantity(w01_runtime, tmp_path, kind, currency):
    runtime, store, plan = fixture(w01_runtime, tmp_path, kind, currency=currency)
    applied = _invoke(runtime, store, plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(plan, json.loads(applied.stdout))["classification"] == "applied"
    row = _inspect(runtime, store, tmp_path, "ReconcileTransaction", plan["operations"][0]["transaction_gid"])
    units = kind == "adjust_asset_quantity"
    assert row["attributes"]["amount"] == (0 if units else 0.01)
    assert row["attributes"]["numberOfShares"] == (0.00000001 if units else 0)
    assert row["attributes"]["reconcileNumberOfShares"] == (1.01500001 if units else 0)
    assert row["attributes"]["reconcileAmount"] == (0 if units else 100.01)
    assert row["account_balance"] == 0
    replay = _invoke(runtime, store, plan, tmp_path)
    assert replay.returncode == 0, replay.stderr
    assert validate_result(plan, json.loads(replay.stdout))["classification"] == "noop"


@pytest.mark.parametrize("kind", ["adjust_account_balance", "adjust_investment_cash", "adjust_asset_quantity"])
@pytest.mark.parametrize("crash,classification", [("before-save", "retry_safe"), ("after-save", "noop")])
def test_w05_extended_crash_recovery(w01_runtime, tmp_path, kind, crash, classification):
    runtime, store, plan = fixture(w01_runtime, tmp_path, kind)
    crash_runtime = replace(runtime, host=runtime.fixture_builder, environment={
        **runtime.environment, "MONEYWIZ_TEST_CRASH_POINT": crash,
    })
    interrupted = _invoke(crash_runtime, store, plan, tmp_path)
    assert interrupted.returncode == (86 if crash == "before-save" else 87), interrupted.stderr
    recovered = _invoke(runtime, store, plan, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(plan, json.loads(recovered.stdout))["classification"] == classification


@pytest.mark.parametrize("kind", ["adjust_account_balance", "adjust_investment_cash", "adjust_asset_quantity"])
@pytest.mark.parametrize("recover", [False, True])
def test_w05_extended_unmarked_store_refusal(w01_runtime, tmp_path, kind, recover):
    runtime, store, plan = fixture(w01_runtime, tmp_path, kind, marked=False)
    refused = _invoke(runtime, store, plan, tmp_path, recover=recover)
    assert refused.returncode != 0
    assert "marked disposable fixture required" in refused.stderr


@pytest.mark.parametrize("field,value", [
    ("holding_gid", "missing"), ("holding_symbol", "BTC"),
    ("asset_type", 0),
    ("expected_prior_balance", "1.016"), ("expected_prior_cash", "99"),
    ("occurred_at", "2026-09-10T09:00:00Z"),
])
def test_w05_quantity_stale_or_wrong_reference(w01_runtime, tmp_path, field, value):
    runtime, store, plan = fixture(w01_runtime, tmp_path, "adjust_asset_quantity")
    operation = plan["operations"][0]
    operation[field] = value
    operation["expected_postcondition"][field] = value
    if field == "expected_prior_balance":
        operation["expected_balance_delta"] = "-0.00099999"
        operation["expected_postcondition"]["expected_balance_delta"] = "-0.00099999"
    plan["plan_digest"] = compute_digest(plan)
    refused = _invoke(runtime, store, plan, tmp_path)
    assert refused.returncode != 0


def test_w05_native_direct_type_and_whitespace_validation(w01_runtime, tmp_path):
    runtime, store, plan = fixture(w01_runtime, tmp_path, "adjust_account_balance")
    for value in [True, 1, "\x1c", " TEST", "TEST ", "\u00a0TEST", "TEST\x1f"]:
        operation = plan["operations"][0]
        operation["description"] = value
        operation["expected_postcondition"]["description"] = value
        plan["plan_digest"] = compute_digest(plan)
        refused = _invoke(runtime, store, plan, tmp_path)
        assert refused.returncode != 0


@pytest.mark.parametrize("kind,entity", [
    ("adjust_account_balance", "BankChequeAccount"),
    ("adjust_investment_cash", "InvestmentAccount"),
    ("adjust_asset_quantity", "ForexAccount"),
    ("adjust_asset_quantity", "InvestmentAccount"),
])
def test_w05_installed_cli_planning_journal_apply_and_recovery(w01_runtime, tmp_path, kind, entity):
    bundle = os.environ.get("MONEYWIZ_TEST_BUNDLE_PATH")
    if not bundle:
        pytest.skip("set MONEYWIZ_TEST_BUNDLE_PATH for installed W05 evidence")
    runtime, store, expected = fixture(w01_runtime, tmp_path, kind, entity=entity)
    payload = request(kind)
    payload.update({key: expected[key] for key in _ENVELOPE_FIELDS})
    operation = expected["operations"][0]
    payload["operation"] = {key: operation[key] for key in payload["operation"]}
    source, plan_file = tmp_path / "request.json", tmp_path / "plan.json"
    source.write_text(json.dumps(payload))
    launcher = Path(bundle) / "Contents/Resources/runtime/moneywiz.sh"
    environment = {**runtime.environment, "MONEYWIZ_JOURNAL_DIR": str(tmp_path / "journal")}
    planned = subprocess.run([str(launcher), "--db", str(store), "transaction", "adjust-balance",
                              "--request", str(source), "--plan", str(plan_file)],
                             env=environment, capture_output=True, text=True)
    assert planned.returncode == 0, planned.stderr
    plan = json.loads(plan_file.read_text())
    assert plan == expected
    owner_id = plan["owner_uri"].rsplit("/p", 1)[1]
    for index, action in enumerate(["apply", "apply", "recover"]):
        command = [str(launcher), "--db", str(store), "write", action, "--plan", str(plan_file),
                   "--app", str(runtime.app), "--owner", owner_id]
        if action == "apply":
            command += ["--apply", "--reviewed-digest", plan["plan_digest"]]
        result = subprocess.run(command, env=environment, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        receipt = validate_result(plan, json.loads(result.stdout))
        assert receipt["classification"] == ("applied" if index == 0 else "noop")
    assert (tmp_path / "journal").is_dir()
