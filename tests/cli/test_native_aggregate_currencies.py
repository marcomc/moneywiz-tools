"""Aggregate totals use the installed app's currency catalogs on every path."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from decimal import Decimal

import pytest

from test_adjust_balance import request
from test_native_delete_adjustment import _invoke, _request as deletion_request, _store
from test_native_transaction_create import W01Runtime, w01_runtime
from write_plan import compute_digest, validate_result
from write_transactions import build_adjust_balance_plan, build_delete_adjustment_plan


def currency_store(runtime, tmp_path, currency, *, marked=True):
    runtime = replace(runtime, environment={**runtime.environment, "MONEYWIZ_TEST_CURRENCY": currency})
    store, identity = _store(runtime, tmp_path, marked=marked)
    return runtime, store, identity


def adjustment(runtime, identity, currency, precision, amount="1"):
    candidate = request()
    candidate.update(app_identity=runtime.app_identity, store_identity={"store_uuid": identity["store_uuid"]},
                     owner_uri=identity["owner_uri"], expected_account_gid="w06-investment",
                     currency_unit=currency, timezone="UTC")
    candidate["operation"].update(account_gid="w06-investment", expected_prior_balance="108",
                                  target_balance=format(Decimal("108") + Decimal(amount), "f"),
                                  occurred_at="2026-09-13T10:00:00Z", currency_precision=precision,
                                  reporting_exchange_rate="0.75")
    return build_adjust_balance_plan(candidate)


def rows(store):
    with sqlite3.connect(f"{store.as_uri()}?mode=ro", uri=True) as connection:
        return connection.execute("SELECT * FROM ZSYNCOBJECT ORDER BY Z_PK").fetchall()


@pytest.mark.parametrize("currency,precision,amount", [
    ("JPY", 0, "1"), ("EUR", 2, "0.01"), ("BHD", 3, "0.001"),
    ("XAU", 6, "0.000001"), ("BTC", 8, "0.12345678"), ("PI+35697", 8, "0.00000001"),
])
def test_native_total_apply_recover_replay_and_delete(w01_runtime: W01Runtime, tmp_path, currency, precision, amount):
    runtime, store, identity = currency_store(w01_runtime, tmp_path, currency)
    before = rows(store)
    plan = adjustment(runtime, identity, currency, precision, amount)
    recovered = _invoke(runtime, store, plan, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(plan, json.loads(recovered.stdout))["classification"] == "retry_safe"
    applied = _invoke(runtime, store, plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    receipt = validate_result(plan, json.loads(applied.stdout))
    assert receipt["classification"] == "applied"
    for recover in [False, True]:
        replay = _invoke(runtime, store, plan, tmp_path, recover=recover)
        assert replay.returncode == 0, replay.stderr
        assert validate_result(plan, json.loads(replay.stdout))["classification"] == "noop"
    with sqlite3.connect(f"{store.as_uri()}?mode=ro", uri=True) as connection:
        assert connection.execute("SELECT ZAMOUNT1,ZRECONCILEAMOUNT,ZCURRENCYEXCHANGERATE FROM ZSYNCOBJECT WHERE ZGID=?",
                                  (plan["operations"][0]["transaction_gid"],)).fetchone() == (
            float(amount), float(plan["operations"][0]["target_balance"]), 0.75)
    delete = deletion_request(runtime, identity)
    delete["currency_unit"] = currency
    delete["operation"].update(transaction_gid=plan["operations"][0]["transaction_gid"],
                               transaction_numeric_id=receipt["operations"][0]["durable_numeric_id"],
                               expected_amount=amount, expected_reconcile_amount=plan["operations"][0]["target_balance"],
                               expected_prior_balance=plan["operations"][0]["target_balance"],
                               occurred_at=plan["operations"][0]["occurred_at"],
                               currency_precision=precision, reporting_exchange_rate="0.75")
    deletion = build_delete_adjustment_plan(delete)
    for recover, expected in [(True, "retry_safe"), (False, "applied"), (True, "noop"), (False, "noop")]:
        result = _invoke(runtime, store, deletion, tmp_path, recover=recover)
        assert result.returncode == 0, result.stderr
        assert validate_result(deletion, json.loads(result.stdout))["classification"] == expected
    # Core Data may advance account versions; every financial row is preserved.
    after = rows(store)
    assert len(after) == len(before)
    assert [row[3:] for row in after] == [row[3:] for row in before]


@pytest.mark.parametrize("currency,precision,marked", [
    ("JPY", 2, True), ("EUR", 8, True), ("BTC", 2, True),
    ("UNKNOWN+999999", 8, True),
])
def test_native_catalog_and_disposable_admission_refuse_before_mutation(w01_runtime, tmp_path, currency, precision, marked):
    runtime, store, identity = currency_store(w01_runtime, tmp_path, currency, marked=marked)
    plan = adjustment(runtime, identity, currency, precision)
    before = rows(store)
    for recover in [False, True]:
        for direct in [False, True]:
            result = _invoke(runtime, store, plan, tmp_path, recover=recover, direct=direct)
            assert result.returncode != 0
            assert rows(store) == before


@pytest.mark.parametrize("bad", [True, False, 2.0, "2", None])
def test_native_precision_scalar_refuses_raw_plan(w01_runtime, tmp_path, bad):
    runtime, store, identity = currency_store(w01_runtime, tmp_path, "EUR")
    plan = adjustment(runtime, identity, "EUR", 2)
    plan["operations"][0]["currency_precision"] = bad
    plan["operations"][0]["expected_postcondition"]["currency_precision"] = bad
    plan["plan_digest"] = compute_digest(plan)
    before = rows(store)
    result = _invoke(runtime, store, plan, tmp_path)
    assert result.returncode != 0
    assert rows(store) == before


@pytest.mark.parametrize("recover", [False, True])
@pytest.mark.parametrize("direct", [False, True])
def test_native_total_unmarked_admission_by_edition(w01_runtime, tmp_path, recover, direct):
    runtime, store, identity = currency_store(w01_runtime, tmp_path, "PI+35697", marked=False)
    plan = adjustment(runtime, identity, "PI+35697", 8)
    before = rows(store)
    result = _invoke(runtime, store, plan, tmp_path, recover=recover, direct=direct)
    if runtime.app_identity["bundle_id"] == "com.moneywiz.personalfinance-setapp":
        assert result.returncode == 0, result.stderr
        assert validate_result(plan, json.loads(result.stdout))["classification"] == ("retry_safe" if recover else "applied")
        assert len(rows(store)) == len(before) + (0 if recover else 1)
    else:
        assert result.returncode != 0
        assert rows(store) == before


@pytest.mark.parametrize("crash,classification", [("before-save", "retry_safe"), ("after-save", "noop")])
def test_crypto_total_save_boundary_recovers(w01_runtime, tmp_path, crash, classification):
    runtime, store, identity = currency_store(w01_runtime, tmp_path, "PI+35697")
    plan = adjustment(runtime, identity, "PI+35697", 8, "0.00000001")
    result = _invoke(runtime, store, plan, tmp_path, crash=crash)
    assert result.returncode in {86, 87}, result.stderr
    recovered = _invoke(runtime, store, plan, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(plan, json.loads(recovered.stdout))["classification"] == classification
