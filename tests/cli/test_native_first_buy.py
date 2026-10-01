"""Atomic first Buy creates a native manual holding on disposable model-48 stores."""
from __future__ import annotations

import json
import os
import subprocess
import plistlib
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

from test_investment_plan import first_buy_request
from test_native_investment import new_store, inspect
from test_native_transaction_create import W01Runtime, _invoke, _crash, w01_runtime
from write_plan import NATIVE_HOLDING_TYPES, compute_digest, validate_result, PlanValidationError
from write_transactions import build_investment_plan


def first_buy_plan(runtime: W01Runtime, identity: dict, *, existing: bool = False,
                   holding_type: str = "Stock") -> dict:
    payload = first_buy_request(holding_type=holding_type)
    payload.update(store_identity={"store_uuid": identity["store_uuid"]},
                   owner_uri=identity["owner_uri"], app_identity=runtime.app_identity,
                   expected_account_gid="w08-investment")
    payload["operation"].update(account_gid="w08-investment", payee_gid="w08-payee",
                                tag_gids=["w08-tag"], expected_prior_cash="89" if existing else "100")
    return build_investment_plan(payload)


def sql_inventory(store: Path) -> list:
    with sqlite3.connect(store) as db:
        return db.execute("SELECT * FROM ZSYNCOBJECT ORDER BY Z_PK").fetchall()


@pytest.mark.parametrize("holding_type", sorted(NATIVE_HOLDING_TYPES))
@pytest.mark.parametrize("existing", [False, True])
def test_first_buy_applies_replays_and_recovers(w01_runtime, tmp_path, existing, holding_type):
    store, identity = new_store(w01_runtime, tmp_path, units=existing)
    planned = first_buy_plan(w01_runtime, identity, existing=existing, holding_type=holding_type)
    operation = planned["operations"][0]
    before = _invoke(w01_runtime, store, planned, tmp_path, recover=True)
    assert before.returncode == 0, before.stderr
    assert validate_result(planned, json.loads(before.stdout))["classification"] == "retry_safe"
    applied = _invoke(w01_runtime, store, planned, tmp_path)
    assert applied.returncode == 0, applied.stderr
    receipt = validate_result(planned, json.loads(applied.stdout))
    assert receipt["classification"] == "applied"
    holding_proof = receipt["operations"][0]["holding_creation"]
    with sqlite3.connect(store) as db:
        holding = db.execute("SELECT Z_PK,ZSYMBOL,ZHOLDINGTYPE,ZDESC,ZINVESTMENTOBJECTTYPE,ZOPENNINGNUMBEROFSHARES,ZPRICEPERSHARE,ZMANUALHISTORICALPRICESPERSHARE FROM ZSYNCOBJECT WHERE ZGID=?", (operation["holding_gid"],)).fetchone()
        assert holding[:7] == (int(holding_proof["durable_numeric_id"]), "FIRST", holding_type, "Synthetic first holding", 0, 0, 5)
        archive = plistlib.loads(holding[7])
        assert any(isinstance(value, dict) and value.get("NS.time") == 810950400 for value in archive["$objects"])
        buy = db.execute("SELECT ZINVESTMENTHOLDING,ZNUMBEROFSHARES,ZPRICEPERSHARE1,ZFEE2,ZAMOUNT1 FROM ZSYNCOBJECT WHERE ZGID=?", (operation["transaction_gid"],)).fetchone()
        assert buy == (holding[0], 2, 5, 1, -11)
    assert inspect(w01_runtime, store, planned, tmp_path)["account_balance"] == 0
    persisted = sql_inventory(store)
    for recovering in [False, True]:
        result = _invoke(w01_runtime, store, planned, tmp_path, recover=recovering)
        assert result.returncode == 0, result.stderr
        assert validate_result(planned, json.loads(result.stdout))["classification"] == "noop"
        assert sql_inventory(store) == persisted
    tampered = deepcopy(receipt)
    tampered["operations"][0]["holding_creation"]["durable_uri"] += "1"
    with pytest.raises(PlanValidationError, match="holding"):
        validate_result(planned, tampered)


@pytest.mark.parametrize("mutation", ["duplicate-symbol", "gid-collision", "stale-cash", "wrong-owner"])
def test_first_buy_refuses_preexisting_or_stale_state(w01_runtime, tmp_path, mutation):
    store, identity = new_store(w01_runtime, tmp_path, units=True)
    planned = first_buy_plan(w01_runtime, identity, existing=True)
    with sqlite3.connect(store) as db:
        if mutation == "duplicate-symbol":
            db.execute("UPDATE ZSYNCOBJECT SET ZSYMBOL='first' WHERE ZGID='w08-holding'")
        elif mutation == "gid-collision":
            db.execute("UPDATE ZSYNCOBJECT SET ZGID=? WHERE ZGID='w08-payee'", (planned["operations"][0]["holding_gid"],))
        elif mutation == "stale-cash":
            db.execute("UPDATE ZSYNCOBJECT SET ZOPENINGBALANCE=101 WHERE ZGID='w08-investment'")
        else:
            planned["owner_uri"] = planned["owner_uri"].rsplit('/p', 1)[0] + '/p99'
            planned["operations"][0]["owner_uri"] = planned["owner_uri"]
            planned["operations"][0]["expected_postcondition"]["owner_uri"] = planned["owner_uri"]
            # Preserve the deterministic source identity in this altered envelope.
            from write_plan import deterministic_transaction_gid
            gid = deterministic_transaction_gid(store_uuid=identity["store_uuid"], owner_uri=planned["owner_uri"], source_event_id=planned["source_event_id"])
            planned["operations"][0]["transaction_gid"] = gid
            planned["operations"][0]["expected_postcondition"]["transaction_gid"] = gid
            planned["plan_digest"] = compute_digest(planned)
    before = sql_inventory(store)
    result = _invoke(w01_runtime, store, planned, tmp_path)
    assert result.returncode == 2
    assert sql_inventory(store) == before


@pytest.mark.parametrize("crash_point,classification", [("before-save", "retry_safe"), ("after-save", "noop")])
def test_first_buy_crash_recovery_is_atomic(w01_runtime, tmp_path, crash_point, classification):
    store, identity = new_store(w01_runtime, tmp_path, units=False)
    planned = first_buy_plan(w01_runtime, identity)
    before = sql_inventory(store)
    crashed = _crash(w01_runtime, store, planned, tmp_path, "--crash-" + crash_point)
    assert crashed.returncode == (86 if crash_point == "before-save" else 87), crashed.stderr
    recovered = _invoke(w01_runtime, store, planned, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(planned, json.loads(recovered.stdout))["classification"] == classification
    if classification == "retry_safe":
        assert sql_inventory(store) == before
    else:
        with sqlite3.connect(store) as db:
            assert db.execute("SELECT COUNT(*) FROM ZSYNCOBJECT WHERE ZGID IN (?,?)", (planned["operations"][0]["holding_gid"],planned["operations"][0]["transaction_gid"])).fetchone()[0] == 2


@pytest.mark.parametrize("missing", ["holding", "buy"])
def test_first_buy_refuses_partial_persisted_state(w01_runtime, tmp_path, missing):
    store, identity = new_store(w01_runtime, tmp_path, units=False)
    planned = first_buy_plan(w01_runtime, identity)
    applied = _invoke(w01_runtime, store, planned, tmp_path)
    assert applied.returncode == 0, applied.stderr
    with sqlite3.connect(store) as db:
        gid = planned["operations"][0]["holding_gid" if missing == "holding" else "transaction_gid"]
        db.execute("DELETE FROM ZSYNCOBJECT WHERE ZGID=?", (gid,))
    before = sql_inventory(store)
    recovered = _invoke(w01_runtime, store, planned, tmp_path, recover=True)
    assert recovered.returncode == 2
    assert sql_inventory(store) == before


def test_first_buy_refuses_forex_new_holding(w01_runtime, tmp_path):
    store, identity = new_store(w01_runtime, tmp_path, units=False, account_entity="ForexAccount")
    planned = first_buy_plan(w01_runtime, identity)
    before = sql_inventory(store)
    result = _invoke(w01_runtime, store, planned, tmp_path)
    assert result.returncode == 2
    assert "Forex creation requires native Exchange" in result.stderr
    assert sql_inventory(store) == before


def test_installed_first_buy_plans_applies_journals_and_enforces_admission(w01_runtime, tmp_path):
    configured = os.environ.get("MONEYWIZ_TEST_BUNDLE_PATH")
    if not configured:
        pytest.skip("set MONEYWIZ_TEST_BUNDLE_PATH for installed first Buy acceptance")
    launcher = Path(configured).resolve() / "Contents/Resources/runtime/moneywiz.sh"
    environment = dict(w01_runtime.environment)
    environment["MONEYWIZ_JOURNAL_DIR"] = str(tmp_path / "journal")
    for name in ("PYTHONPATH", "MONEYWIZ_TOOLS_HOST", "MONEYWIZ_CORE_DATA_WRITER"):
        environment.pop(name, None)

    def run(store, *args):
        return subprocess.run([str(launcher), "--db", str(store), *args], cwd=tmp_path,
                              env=environment, capture_output=True, text=True)

    marked_dir = tmp_path / "marked"
    marked_dir.mkdir()
    store, identity = new_store(w01_runtime, marked_dir, units=False)
    expected = first_buy_plan(w01_runtime, identity)
    from write_transactions import _ENVELOPE_FIELDS
    payload = {key: expected[key] for key in _ENVELOPE_FIELDS}
    payload["operation"] = {key: expected["operations"][0][key] for key in first_buy_request()["operation"]}
    payload["operation"]["holding_gid"] = None
    request_file, plan_file = tmp_path / "request.json", tmp_path / "plan.json"
    request_file.write_text(json.dumps(payload), encoding="utf-8")
    planned = run(store, "transaction", "investment", "--request", str(request_file), "--plan", str(plan_file))
    assert planned.returncode == 0, planned.stderr
    assert json.loads(planned.stdout)["plan_digest"] == expected["plan_digest"]
    common = ["--plan", str(plan_file), "--app", str(w01_runtime.app), "--model", str(w01_runtime.model),
              "--owner", identity["owner_uri"].rsplit("/p", 1)[1]]
    apply_args = ["write", "apply", *common, "--reviewed-digest", expected["plan_digest"], "--apply"]
    for expected_status in ["applied", "noop"]:
        applied = run(store, *apply_args)
        assert applied.returncode == 0, applied.stderr
        assert validate_result(expected, json.loads(applied.stdout))["classification"] == expected_status
    recovered = run(store, "write", "recover", *common)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(expected, json.loads(recovered.stdout))["classification"] == "noop"
    entries = run(store, "write", "journal")
    assert entries.returncode == 0, entries.stderr
    assert len(json.loads(entries.stdout)["entries"]) == 1
    assert json.loads(entries.stdout)["entries"][0]["state"] == "verified"

    unmarked_dir = tmp_path / "unmarked"
    unmarked_dir.mkdir()
    unmarked, unmarked_identity = new_store(w01_runtime, unmarked_dir, units=False, marked=False)
    rejected = first_buy_plan(w01_runtime, unmarked_identity)
    rejected_file = tmp_path / "unmarked-plan.json"
    rejected_file.write_text(json.dumps(rejected), encoding="utf-8")
    before = sql_inventory(unmarked)
    refused = run(unmarked, "write", "apply", "--plan", str(rejected_file), "--app", str(w01_runtime.app),
                  "--model", str(w01_runtime.model), "--owner", unmarked_identity["owner_uri"].rsplit("/p", 1)[1],
                  "--reviewed-digest", rejected["plan_digest"], "--apply")
    assert refused.returncode == 2
    assert "disposable" in refused.stderr
    native_refused = _invoke(w01_runtime, unmarked, rejected, unmarked_dir)
    assert native_refused.returncode == 2
    assert "disposable" in native_refused.stderr
    assert sql_inventory(unmarked) == before
