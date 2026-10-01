"""W08 writes only to freshly marked disposable model-48 stores."""

from __future__ import annotations

import json
import subprocess
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import writer_client

from test_investment_plan import request as investment_request
from test_native_transaction_create import W01Runtime, _crash, _invoke, w01_runtime
from write_journal import JournalPaths, JournalStore
from write_plan import validate_result
from write_transactions import build_investment_plan
from writer_client import WriterClient, WriterClientError


def new_store(runtime: W01Runtime, directory: Path, *, units: bool,
              marked: bool = True, account_entity: str = "InvestmentAccount") -> tuple[Path, dict]:
    store = directory / "w08-disposable.sqlite"
    flag = "--w08-units" if units else "--w08-aggregate"
    if not marked:
        flag = "--w08-unmarked"
    completed = subprocess.run(
        [str(runtime.fixture_builder), "--store", str(store), "--model",
         str(runtime.model), flag],
        cwd=directory, env={**runtime.environment, "MONEYWIZ_TEST_ACCOUNT_ENTITY": account_entity}, capture_output=True, text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return store, json.loads(completed.stdout)


def plan(runtime: W01Runtime, identity: dict, kind: str,
         *, aggregate: bool = False, investment_symbol: str | None = None) -> dict:
    value = investment_request(kind, aggregate=aggregate)
    value.update(
        plan_id=f"w08-{kind}",
        store_identity={"store_uuid": identity["store_uuid"]},
        owner_uri=identity["owner_uri"],
        app_identity=runtime.app_identity,
        source_event_id=f"w08-{kind}",
        expected_account_gid="w08-investment",
    )
    value["operation"].update(
        account_gid="w08-investment",
        payee_gid="w08-payee",
        tag_gids=["w08-tag"],
        investment_symbol=investment_symbol,
    )
    if kind == "investment_income":
        value["operation"]["category_splits"] = [
            {"category_gid": "w08-income", "amount": "2"}
        ]
    if kind == "investment_expense":
        value["operation"]["category_splits"] = [
            {"category_gid": "w08-expense", "amount": "-2"}
        ]
    if kind.endswith(("buy", "sell")):
        value["operation"].update(holding_gid="w08-holding", holding_symbol="W08")
    return build_investment_plan(value)


def inspect(runtime: W01Runtime, store: Path, write_plan: dict,
            directory: Path) -> dict:
    operation = write_plan["operations"][0]
    completed = subprocess.run(
        [str(runtime.fixture_builder), "--inspect", "--store", str(store),
         "--model", str(runtime.model), "--entity", operation["transaction_entity"],
         "--gid", operation["transaction_gid"]],
        cwd=directory, env=runtime.environment, capture_output=True, text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.parametrize("account_entity", ["InvestmentAccount", "ForexAccount"])
@pytest.mark.parametrize("kind,aggregate", [
    ("investment_income", True),
    ("investment_expense", False),
    ("investment_buy", False),
    ("investment_sell", False),
])
def test_w08_applies_replays_and_recovers(
    w01_runtime: W01Runtime, tmp_path: Path, kind: str, aggregate: bool, account_entity: str
) -> None:
    store, identity = new_store(w01_runtime, tmp_path, units=not aggregate, account_entity=account_entity)
    write_plan = plan(w01_runtime, identity, kind, aggregate=aggregate)
    before = _invoke(w01_runtime, store, write_plan, tmp_path, recover=True)
    assert before.returncode == 0, before.stderr
    assert validate_result(write_plan, json.loads(before.stdout))["classification"] == "retry_safe"
    applied = _invoke(w01_runtime, store, write_plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(write_plan, json.loads(applied.stdout))["classification"] == "applied"
    persisted = inspect(w01_runtime, store, write_plan, tmp_path)
    attributes = persisted["attributes"]
    operation = write_plan["operations"][0]
    assert persisted["account_balance"] == 0
    assert attributes["status"] == 2
    assert attributes["flags"] == 0
    assert attributes["reconciled"] == 1
    assert attributes["amount"] == float(operation["amount"])
    assert attributes["originalAmount"] == float(operation["amount"])
    if kind.endswith(("buy", "sell")):
        assert attributes["numberOfShares"] == 2
        assert attributes["pricePerShare"] == 5
        assert attributes["fee"] == 1
        assert attributes["originalFee"] == 0
        assert attributes["originalFeeCurrency"] is None
        assert attributes["investmentSymbol"] is None
        assert attributes["symbol"] == "W08"
        assert attributes["currencyExchangeRate"] == 0
        assert attributes["originalExchangeRate"] == 0
    else:
        assert attributes["currencyExchangeRate"] == 1
        assert attributes["originalExchangeRate"] == 1
    replay = _invoke(w01_runtime, store, write_plan, tmp_path)
    assert replay.returncode == 0, replay.stderr
    assert validate_result(write_plan, json.loads(replay.stdout))["classification"] == "noop"
    recovered = _invoke(w01_runtime, store, write_plan, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(write_plan, json.loads(recovered.stdout))["classification"] == "noop"


def test_w08_cash_event_preserves_explicit_investment_symbol(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = new_store(w01_runtime, tmp_path, units=False)
    write_plan = plan(w01_runtime, identity, "investment_income", aggregate=True,
                      investment_symbol="DIV")
    applied = _invoke(w01_runtime, store, write_plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(write_plan, json.loads(applied.stdout))["classification"] == "applied"
    assert inspect(w01_runtime, store, write_plan, tmp_path)["attributes"]["investmentSymbol"] == "DIV"


@pytest.mark.parametrize("field,value", [
    ("expected_prior_cash", "88"),
    ("expected_prior_units", "1"),
    ("holding_gid", "missing-holding"),
    ("holding_symbol", "OTHER"),
    ("asset_type", 2),
])
def test_w08_native_preflight_rejects_stale_or_wrong_holding(
    w01_runtime: W01Runtime, tmp_path: Path, field: str, value: object
) -> None:
    store, identity = new_store(w01_runtime, tmp_path, units=True)
    payload = investment_request("investment_buy")
    payload.update(
        plan_id="w08-negative", store_identity={"store_uuid": identity["store_uuid"]},
        owner_uri=identity["owner_uri"], app_identity=w01_runtime.app_identity,
        source_event_id="w08-negative", expected_account_gid="w08-investment",
    )
    payload["operation"].update(
        account_gid="w08-investment", payee_gid="w08-payee", tag_gids=["w08-tag"],
        holding_gid="w08-holding", holding_symbol="W08",
    )
    payload["operation"][field] = value
    write_plan = build_investment_plan(payload)
    result = _invoke(w01_runtime, store, write_plan, tmp_path)
    assert result.returncode == 2
    assert "W08" in result.stderr or "expected one InvestmentHolding" in result.stderr


def test_w08_rejects_unmarked_store(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = new_store(w01_runtime, tmp_path, units=False, marked=False)
    write_plan = plan(w01_runtime, identity, "investment_income", aggregate=True)
    result = _invoke(w01_runtime, store, write_plan, tmp_path)
    assert result.returncode == 2
    assert "marked disposable fixture required" in result.stderr


def test_w08_writer_client_journals_and_recovers(
    w01_runtime: W01Runtime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, identity = new_store(w01_runtime, tmp_path, units=True)
    write_plan = plan(w01_runtime, identity, "investment_buy")
    monkeypatch.setenv("HOME", w01_runtime.environment["HOME"])
    monkeypatch.setattr(writer_client, "require_moneywiz_stopped", lambda: None)
    journal = JournalStore(JournalPaths.from_environ({
        "MONEYWIZ_JOURNAL_DIR": str(tmp_path / "journal"),
    }))
    client = WriterClient(w01_runtime.fixture_builder, w01_runtime.model, store)
    assert client.apply(write_plan, write_plan["plan_digest"], journal)["classification"] == "applied"
    assert client.apply(write_plan, write_plan["plan_digest"], journal)["classification"] == "noop"
    assert client.recover(write_plan, journal)["classification"] == "noop"
    assert journal.load(write_plan["plan_id"])["state"] == "verified"


def test_w08_writer_client_refuses_unmarked_store_before_journal(
    w01_runtime: W01Runtime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, identity = new_store(w01_runtime, tmp_path, units=False, marked=False)
    write_plan = plan(w01_runtime, identity, "investment_income", aggregate=True)
    monkeypatch.setenv("HOME", w01_runtime.environment["HOME"])
    monkeypatch.setattr(writer_client, "require_moneywiz_stopped", lambda: None)
    journal = JournalStore(JournalPaths.from_environ({
        "MONEYWIZ_JOURNAL_DIR": str(tmp_path / "journal"),
    }))
    client = WriterClient(w01_runtime.fixture_builder, w01_runtime.model, store)
    with pytest.raises(WriterClientError, match="disposable"):
        client.apply(write_plan, write_plan["plan_digest"], journal)
    assert not list(journal.entries.iterdir())


@pytest.mark.parametrize("boundary,expected", [
    ("--crash-before-save", "retry_safe"),
    ("--crash-after-save", "noop"),
])
def test_w08_crash_boundary_recovers(
    w01_runtime: W01Runtime, tmp_path: Path, boundary: str, expected: str
) -> None:
    store, identity = new_store(w01_runtime, tmp_path, units=True)
    write_plan = plan(w01_runtime, identity, "investment_buy")
    crashed = _crash(w01_runtime, store, write_plan, tmp_path, boundary)
    assert crashed.returncode == (86 if boundary == "--crash-before-save" else 87)
    recovered = _invoke(w01_runtime, store, write_plan, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(write_plan, json.loads(recovered.stdout))["classification"] == expected


def test_cash_ledger_rounds_native_double_residue_to_cents(w01_runtime, tmp_path):
    store, identity = new_store(w01_runtime, tmp_path, units=False)
    with sqlite3.connect(store) as connection:
        connection.execute("UPDATE ZSYNCOBJECT SET ZOPENINGBALANCE=? WHERE ZGID=?",
                           (100.00000000000001, "w08-investment"))
    request = investment_request("investment_income", aggregate=True)
    request.update(store_identity={"store_uuid": identity["store_uuid"]},
                   owner_uri=identity["owner_uri"], app_identity=w01_runtime.app_identity,
                   expected_account_gid="w08-investment")
    request["operation"].update(account_gid="w08-investment", payee_gid="w08-payee",
                                tag_gids=[], category_splits=[{"category_gid":"w08-income", "amount":"2"}],
                                description="TEST W08 visible description")
    write_plan = build_investment_plan(request)
    applied = _invoke(w01_runtime, store, write_plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(write_plan, json.loads(applied.stdout))["classification"] == "applied"
    assert inspect(w01_runtime, store, write_plan, tmp_path)["attributes"]["desc"] == "TEST W08 visible description"
    with sqlite3.connect(store) as connection:
        assert connection.execute("SELECT ZOPENINGBALANCE FROM ZSYNCOBJECT WHERE ZGID=?",
                                  ("w08-investment",)).fetchone()[0] == 100.00000000000001
