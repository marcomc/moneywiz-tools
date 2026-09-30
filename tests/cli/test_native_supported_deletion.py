"""Read-only W06 closure and financial projection on an invented model-48 store."""

from __future__ import annotations

import json
import os
import plistlib
import sqlite3
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from test_native_transaction_create import W01Runtime, w01_runtime
from test_transaction_create import request
from write_plan import PlanValidationError, compute_digest, validate_plan, validate_result
from write_transactions import build_supported_deletion_plan


def _store(runtime: W01Runtime, directory: Path, **environment: str) -> tuple[Path, dict]:
    store = directory / "w06-supported.sqlite"
    result = subprocess.run(
        [str(runtime.fixture_builder), "--store", str(store),
         "--model", str(runtime.model), "--w06-supported"],
        cwd=directory, env={**runtime.environment, **environment}, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return store, json.loads(result.stdout)


def _inventory(runtime: W01Runtime, store: Path, *gids: str) -> subprocess.CompletedProcess[str]:
    arguments = [str(runtime.host), "--coredata-deletion-inventory",
                 "--store", str(store), "--model", str(runtime.model)]
    for gid in gids:
        arguments.extend(("--target", gid))
    return subprocess.run(arguments, cwd=store.parent, env=runtime.environment,
                          capture_output=True, text=True, check=False)


def _snapshot(store: Path) -> str:
    with sqlite3.connect(f"{store.as_uri()}?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        return "\n".join(connection.iterdump())


def _plan(runtime: W01Runtime, store: Path, identity: dict, *gids: str) -> dict:
    result = _inventory(runtime, store, *gids)
    assert result.returncode == 0, result.stderr
    inventory = json.loads(result.stdout)
    payload = request()
    primary = inventory["targets"][0]
    account = next(item for item in inventory["accounts"] if item["gid"] == primary["account_gid"])
    payload.update(
        plan_id="w06-supported-plan", store_identity={"store_uuid": identity["store_uuid"]},
        owner_uri=identity["owner_uri"], app_identity=runtime.app_identity,
        expected_account_gid=account["gid"], expected_cached_account_balance=account["prior_cache"],
        currency_unit=account["currency"],
        operation={"operation_id": "delete-1", "kind": "delete_supported_transactions",
                   "deletion_reason": "Remove fictional test rows", "deletion_inventory": inventory},
    )
    return build_supported_deletion_plan(payload)


def _invoke(runtime: W01Runtime, store: Path, plan: dict, *, recover: bool = False,
            crash: str | None = None, direct: bool = False) -> subprocess.CompletedProcess[str]:
    plan_file = store.parent / "w06-plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    environment = {**runtime.environment}
    if crash:
        environment["MONEYWIZ_TEST_CRASH_POINT"] = crash
    return subprocess.run(
        [str(runtime.fixture_builder if crash or direct else runtime.host),
         "--coredata-recover" if recover else "--coredata-write",
         "--store", str(store), "--model", str(runtime.model), "--plan", str(plan_file)],
        cwd=store.parent, env=environment, capture_output=True, text=True, check=False,
    )


def _classification(plan: dict, completed: subprocess.CompletedProcess[str]) -> str:
    assert completed.returncode == 0, completed.stderr
    return validate_result(plan, json.loads(completed.stdout))["classification"]


def test_inventory_binds_assignment_and_preserves_shared_objects(
    w01_runtime: W01Runtime, tmp_path: Path,
) -> None:
    store, identity = _store(w01_runtime, tmp_path)
    before = _snapshot(store)
    result = _inventory(w01_runtime, store, "w06-categorized")
    assert result.returncode == 0, result.stderr
    inventory = json.loads(result.stdout)
    assert inventory["owner_uri"] == identity["owner_uri"]
    assert [target["object"]["gid"] for target in inventory["targets"]] == ["w06-categorized"]
    assert [child["entity"] for child in inventory["dependents"]] == ["CategoryAssigment"]
    retained = {item.get("gid"): item for item in inventory["retained"]}
    for gid in ("w06-payee", "w06-tag", "w06-category", "w06-account"):
        assert retained[gid]["fingerprint"] != retained[gid]["final_fingerprint"]
    assert retained["w06-income"]["fingerprint"] == retained["w06-income"]["final_fingerprint"]
    account = inventory["accounts"][0]
    assert (account["prior_balance"], account["final_balance"]) == ("91", "95")
    assert (account["prior_cache"], account["final_cache"]) == ("0", "4")
    assert _snapshot(store) == before
    repeated = _inventory(w01_runtime, store, "w06-categorized")
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout) == inventory


def test_refund_only_keeps_original_and_sibling_refund(
    w01_runtime: W01Runtime, tmp_path: Path,
) -> None:
    store, _ = _store(w01_runtime, tmp_path)
    result = _inventory(w01_runtime, store, "w06-refund-1")
    assert result.returncode == 0, result.stderr
    inventory = json.loads(result.stdout)
    assert [child["entity"] for child in inventory["dependents"]] == ["WithdrawRefundTransactionLink"]
    retained = {item.get("gid"): item for item in inventory["retained"]}
    assert retained["w06-expense"]["fingerprint"] != retained["w06-expense"]["final_fingerprint"]
    assert retained["w06-refund-2"]["fingerprint"] == retained["w06-refund-2"]["final_fingerprint"]
    assert inventory["accounts"][0]["final_balance"] == "89"


def test_explicit_withdrawal_and_refund_closure(
    w01_runtime: W01Runtime, tmp_path: Path,
) -> None:
    store, _ = _store(w01_runtime, tmp_path)
    result = _inventory(w01_runtime, store, "w06-expense", "w06-refund-1", "w06-refund-2")
    assert result.returncode == 0, result.stderr
    inventory = json.loads(result.stdout)
    assert sorted(child["entity"] for child in inventory["dependents"]) == [
        "CategoryAssigment", "WithdrawRefundTransactionLink", "WithdrawRefundTransactionLink",
    ]
    assert inventory["accounts"][0]["final_balance"] == "96"


def test_reciprocal_transfer_projection_covers_both_accounts(
    w01_runtime: W01Runtime, tmp_path: Path,
) -> None:
    store, _ = _store(w01_runtime, tmp_path)
    result = _inventory(w01_runtime, store, "w06-send", "w06-receive")
    assert result.returncode == 0, result.stderr
    inventory = json.loads(result.stdout)
    accounts = {item["gid"]: item for item in inventory["accounts"]}
    assert set(accounts) == {"w06-account", "w06-recipient"}
    assert accounts["w06-account"]["final_balance"] == "96"
    assert accounts["w06-recipient"]["final_balance"] == "50"
    reverse = _inventory(w01_runtime, store, "w06-receive", "w06-send")
    assert reverse.returncode == 0, reverse.stderr
    assert json.loads(reverse.stdout) == inventory


def test_investment_projection_keeps_holding_and_checks_units(
    w01_runtime: W01Runtime, tmp_path: Path,
) -> None:
    store, _ = _store(w01_runtime, tmp_path)
    result = _inventory(w01_runtime, store, "w06-buy", "w06-sell")
    assert result.returncode == 0, result.stderr
    inventory = json.loads(result.stdout)
    assert (inventory["accounts"][0]["prior_balance"], inventory["accounts"][0]["final_balance"]) == ("120", "100")
    assert (inventory["holdings"][0]["prior_units"], inventory["holdings"][0]["final_units"]) == ("1", "3")
    assert not inventory["dependents"]
    assert "w06-holding" in {item.get("gid") for item in inventory["retained"]}


@pytest.mark.parametrize("order", ["forward", "reverse"])
def test_deletion_preserves_native_dated_historical_prices(
    w01_runtime: W01Runtime, tmp_path: Path, order: str,
) -> None:
    store, identity = _store(w01_runtime, tmp_path, MONEYWIZ_TEST_HISTORICAL_PRICES=order)
    plan = _plan(w01_runtime, store, identity, "w06-buy", "w06-sell")
    retained = plan["operations"][0]["deletion_inventory"]["retained"]
    holding = next(item for item in retained if item.get("gid") == "w06-holding")
    assert holding["fingerprint"] != holding["final_fingerprint"]  # trade inverses disappear
    repeated = _plan(w01_runtime, store, identity, "w06-sell", "w06-buy")
    assert repeated == plan
    with sqlite3.connect(f"{store.as_uri()}?mode=ro", uri=True) as db:
        before = db.execute(
            "SELECT ZMANUALHISTORICALPRICESPERSHARE FROM ZSYNCOBJECT WHERE ZGID='w06-holding'"
        ).fetchone()[0]
    assert _classification(plan, _invoke(w01_runtime, store, plan)) == "applied"
    assert _classification(plan, _invoke(w01_runtime, store, plan, recover=True)) == "noop"
    with sqlite3.connect(f"{store.as_uri()}?mode=ro", uri=True) as db:
        assert db.execute(
            "SELECT ZMANUALHISTORICALPRICESPERSHARE FROM ZSYNCOBJECT WHERE ZGID='w06-holding'"
        ).fetchone()[0] == before


def test_deletion_refuses_unreviewed_historical_price_keys_without_mutation(
    w01_runtime: W01Runtime, tmp_path: Path,
) -> None:
    store, _ = _store(w01_runtime, tmp_path, MONEYWIZ_TEST_HISTORICAL_PRICES="numeric-key")
    before = _snapshot(store)
    result = _inventory(w01_runtime, store, "w06-buy", "w06-sell")
    assert result.returncode != 0
    assert "nonstring native dictionary key" in result.stderr
    assert _snapshot(store) == before


def test_changed_historical_price_invalidates_reviewed_deletion(
    w01_runtime: W01Runtime, tmp_path: Path,
) -> None:
    store, identity = _store(w01_runtime, tmp_path, MONEYWIZ_TEST_HISTORICAL_PRICES="forward")
    plan = _plan(w01_runtime, store, identity, "w06-buy", "w06-sell")
    with sqlite3.connect(store) as db:
        encoded = db.execute(
            "SELECT ZMANUALHISTORICALPRICESPERSHARE FROM ZSYNCOBJECT WHERE ZGID='w06-holding'"
        ).fetchone()[0]
        archive = plistlib.loads(encoded)
        indices = [i for i, value in enumerate(archive["$objects"])
                   if type(value) is float and value == 10.5]
        assert len(indices) == 1
        archive["$objects"][indices[0]] = 10.75
        db.execute(
            "UPDATE ZSYNCOBJECT SET ZMANUALHISTORICALPRICESPERSHARE=? WHERE ZGID='w06-holding'",
            (plistlib.dumps(archive, fmt=plistlib.FMT_BINARY),),
        )
    changed = _snapshot(store)
    assert _classification(plan, _invoke(w01_runtime, store, plan, recover=True)) == "unknown"
    assert _invoke(w01_runtime, store, plan).returncode != 0
    assert _snapshot(store) == changed


@pytest.mark.parametrize("value", ["string-price", "bool-price", "infinite-price"])
def test_deletion_refuses_invalid_dated_prices_without_mutation(
    w01_runtime: W01Runtime, tmp_path: Path, value: str,
) -> None:
    store, _ = _store(w01_runtime, tmp_path, MONEYWIZ_TEST_HISTORICAL_PRICES=value)
    before = _snapshot(store)
    result = _inventory(w01_runtime, store, "w06-buy", "w06-sell")
    assert result.returncode != 0
    assert "historical-price value must be a finite number" in result.stderr
    assert _snapshot(store) == before


@pytest.mark.parametrize(("gids", "error"), [
    (("w06-expense",), "explicitly selected dependent refunds"),
    (("w06-expense", "w06-refund-1"), "explicitly selected dependent refunds"),
    (("w06-send",), "reciprocal transfer pair"),
    (("w06-receive",), "reciprocal transfer pair"),
    (("w06-buy",), "negative derived units"),
    (("w06-income", "w06-foreign-income"), "different owners"),
    (("w06-income", "w06-income"), "distinct normalized target GIDs"),
    ((" w06-income",), "distinct normalized target GIDs"),
    (("w06-income\u001c",), "distinct normalized target GIDs"),
    (("missing",), "matched 0 objects"),
])
def test_invalid_closures_are_rejected_without_mutation(
    w01_runtime: W01Runtime, tmp_path: Path, gids: tuple[str, ...], error: str,
) -> None:
    store, _ = _store(w01_runtime, tmp_path)
    before = _snapshot(store)
    result = _inventory(w01_runtime, store, *gids)
    assert result.returncode != 0
    assert error in result.stderr
    assert _snapshot(store) == before


@pytest.mark.parametrize("gids", [
    ("w06-income",), ("w06-categorized",), ("w06-refund-1",),
    ("w06-expense", "w06-refund-1", "w06-refund-2"),
    ("w06-send", "w06-receive"), ("w06-adjustment",),
    ("w06-sell",), ("w06-buy", "w06-sell"),
])
def test_supported_deletion_applies_atomically_and_replays(
    w01_runtime: W01Runtime, tmp_path: Path, gids: tuple[str, ...],
) -> None:
    store, identity = _store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, store, identity, *gids)
    before = _snapshot(store)
    assert _classification(plan, _invoke(w01_runtime, store, plan, recover=True)) == "retry_safe"
    assert _snapshot(store) == before
    assert _classification(plan, _invoke(w01_runtime, store, plan)) == "applied"
    after = _snapshot(store)
    assert after != before
    assert _classification(plan, _invoke(w01_runtime, store, plan, recover=True)) == "noop"
    assert _classification(plan, _invoke(w01_runtime, store, plan)) == "noop"
    assert _snapshot(store) == after


@pytest.mark.parametrize(("crash", "exit_code", "classification"), [
    ("before-save", 86, "retry_safe"), ("after-save", 87, "noop"),
])
def test_supported_deletion_crash_recovery(
    w01_runtime: W01Runtime, tmp_path: Path, crash: str, exit_code: int, classification: str,
) -> None:
    store, identity = _store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, store, identity, "w06-send", "w06-receive", "w06-categorized")
    result = _invoke(w01_runtime, store, plan, crash=crash)
    assert result.returncode == exit_code, result.stderr
    assert _classification(plan, _invoke(w01_runtime, store, plan, recover=True)) == classification
    assert _classification(plan, _invoke(w01_runtime, store, plan)) == (
        "applied" if classification == "retry_safe" else "noop"
    )


def test_retained_attribute_change_invalidates_entire_deletion(
    w01_runtime: W01Runtime, tmp_path: Path,
) -> None:
    store, identity = _store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, store, identity, "w06-income")
    with sqlite3.connect(store) as connection:
        connection.execute("UPDATE ZSYNCOBJECT SET ZDESC2='Changed retained description' WHERE ZGID='w06-categorized'")
    before = _snapshot(store)
    assert _classification(plan, _invoke(w01_runtime, store, plan, recover=True)) == "unknown"
    result = _invoke(w01_runtime, store, plan)
    assert result.returncode != 0
    assert "stale or partially absent" in result.stderr
    assert _snapshot(store) == before


def test_partial_target_absence_refuses_replay(
    w01_runtime: W01Runtime, tmp_path: Path,
) -> None:
    store, identity = _store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, store, identity, "w06-income", "w06-adjustment")
    partial = _plan(w01_runtime, store, identity, "w06-income")
    assert _classification(partial, _invoke(w01_runtime, store, partial)) == "applied"
    before = _snapshot(store)
    assert _classification(plan, _invoke(w01_runtime, store, plan, recover=True)) == "unknown"
    assert _invoke(w01_runtime, store, plan).returncode != 0
    assert _snapshot(store) == before


@pytest.mark.parametrize("recover", [False, True])
def test_direct_supported_deletion_requires_fixture_marker_for_testflight(
    w01_runtime: W01Runtime, tmp_path: Path, recover: bool,
) -> None:
    if w01_runtime.app_identity["bundle_id"] != "com.moneywiz.personalfinance":
        pytest.skip("TestFlight-specific marker boundary")
    store, identity = _store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, store, identity, "w06-income")
    with sqlite3.connect(store) as connection:
        metadata = plistlib.loads(connection.execute("SELECT Z_PLIST FROM Z_METADATA").fetchone()[0])
        del metadata["MoneyWizToolsDisposableFixture"]
        connection.execute("UPDATE Z_METADATA SET Z_PLIST=?", (plistlib.dumps(metadata),))
    before = _snapshot(store)
    result = _invoke(w01_runtime, store, plan, recover=recover, direct=True)
    assert result.returncode != 0
    assert "marked disposable fixture required" in result.stderr
    assert _snapshot(store) == before


@pytest.mark.parametrize("mutation", [
    "asset_type_bool", "asset_type_float", "unknown_inventory_field", "foreign_uri",
    "empty_retained", "primary_gid", "padded_gid", "integer_postcondition",
    "negative_units", "fingerprint", "extra_operation",
])
def test_python_and_direct_native_admission_reject_invalid_deletion_plans(
    w01_runtime: W01Runtime, tmp_path: Path, mutation: str,
) -> None:
    store, identity = _store(w01_runtime, tmp_path)
    plan = deepcopy(_plan(w01_runtime, store, identity, "w06-buy", "w06-sell"))
    operation = plan["operations"][0]
    inventory = operation["deletion_inventory"]
    if mutation == "asset_type_bool":
        inventory["holdings"][0]["asset_type"] = False
    elif mutation == "asset_type_float":
        inventory["holdings"][0]["asset_type"] = 0.0
    elif mutation == "unknown_inventory_field":
        inventory["extra"] = "ignored?"
    elif mutation == "foreign_uri":
        inventory["targets"][0]["object"]["object_uri"] = "x-coredata://other/InvestmentBuyTransaction/p1"
    elif mutation == "empty_retained":
        inventory["retained"] = []
    elif mutation == "primary_gid":
        operation["transaction_gid"] = "different"
    elif mutation == "padded_gid":
        inventory["holdings"][0]["gid"] += "\u001c"
    elif mutation == "integer_postcondition":
        operation["expected_postcondition"]["retained_verified"] = 1
    elif mutation == "negative_units":
        inventory["holdings"][0]["final_units"] = "-1"
    elif mutation == "fingerprint":
        inventory["targets"][0]["object"]["fingerprint"] = "invalid"
    elif mutation == "extra_operation":
        plan["operations"].append(deepcopy(operation))
    plan["plan_digest"] = compute_digest(plan)
    with pytest.raises(PlanValidationError):
        validate_plan(plan)
    before = _snapshot(store)
    for recover in (False, True):
        result = _invoke(w01_runtime, store, plan, recover=recover, direct=True)
        assert result.returncode != 0
        assert _snapshot(store) == before


@pytest.mark.parametrize("entity", [
    "CashAccount", "BankChequeAccount", "BankSavingAccount", "CreditCardAccount",
    "LoanAccount", "InvestmentAccount", "ForexAccount",
])
def test_deletion_supports_reviewed_account_types(
    w01_runtime: W01Runtime, tmp_path: Path, entity: str,
) -> None:
    store, identity = _store(w01_runtime, tmp_path, MONEYWIZ_TEST_ACCOUNT_ENTITY=entity)
    plan = _plan(w01_runtime, store, identity, "w06-income")
    assert _classification(plan, _invoke(w01_runtime, store, plan)) == "applied"


@pytest.mark.parametrize("currency", ["GBP", "EUR", "USD", "CAD"])
def test_deletion_supports_installed_currency_inventory(
    w01_runtime: W01Runtime, tmp_path: Path, currency: str,
) -> None:
    store, identity = _store(w01_runtime, tmp_path, MONEYWIZ_TEST_CURRENCY=currency)
    plan = _plan(w01_runtime, store, identity, "w06-send", "w06-receive")
    assert plan["currency_unit"] == currency
    assert _classification(plan, _invoke(w01_runtime, store, plan)) == "applied"


@pytest.mark.parametrize("entity", ["InvestmentAccount", "ForexAccount"])
def test_quantity_adjustment_deletion_leaves_cash_and_holding_metadata(
    w01_runtime: W01Runtime, tmp_path: Path, entity: str,
) -> None:
    store, identity = _store(w01_runtime, tmp_path, MONEYWIZ_TEST_INVESTMENT_ENTITY=entity,
                            MONEYWIZ_TEST_QUANTITY_ADJUSTMENT="1")
    plan = _plan(w01_runtime, store, identity, "w06-quantity")
    inventory = plan["operations"][0]["deletion_inventory"]
    assert (inventory["holdings"][0]["prior_units"], inventory["holdings"][0]["final_units"]) == ("1.5", "1")
    assert inventory["accounts"][0]["prior_balance"] == inventory["accounts"][0]["final_balance"]
    assert _classification(plan, _invoke(w01_runtime, store, plan)) == "applied"
    assert _classification(plan, _invoke(w01_runtime, store, plan, recover=True)) == "noop"


def test_installed_deletion_cli_and_journal(
    w01_runtime: W01Runtime, tmp_path: Path,
) -> None:
    configured = os.environ.get("MONEYWIZ_TEST_BUNDLE_PATH")
    if not configured:
        pytest.skip("set MONEYWIZ_TEST_BUNDLE_PATH for installed deletion evidence")
    launcher = Path(configured).resolve() / "Contents/Resources/runtime/moneywiz.sh"
    store, identity = _store(w01_runtime, tmp_path)
    environment = {**w01_runtime.environment, "MONEYWIZ_JOURNAL_DIR": str(tmp_path / "journal")}
    for variable in ("MONEYWIZ_TOOLS_HOST", "MONEYWIZ_CORE_DATA_WRITER"):
        environment.pop(variable, None)

    def run(*arguments: str, expected_exit: int = 0) -> dict:
        completed = subprocess.run([str(launcher), "--db", str(store), *arguments],
                                   cwd=tmp_path, env=environment, capture_output=True,
                                   text=True, check=False)
        assert completed.returncode == expected_exit, completed.stderr
        return json.loads(completed.stdout if expected_exit == 0 else completed.stderr)

    plan_file = tmp_path / "installed-delete-plan.json"
    before = _snapshot(store)
    planned = run("transaction", "delete", "--target", "w06-expense",
                  "--target", "w06-refund-1", "--target", "w06-refund-2",
                  "--reason", "Remove fictional installed test rows",
                  "--evidence-note", "synthetic://W06-installed-deletion",
                  "--app", str(w01_runtime.app), "--model", str(w01_runtime.model),
                  "--owner", identity["owner_uri"].rsplit("/p", 1)[1], "--plan", str(plan_file))
    assert _snapshot(store) == before
    assert not (tmp_path / "journal").exists()
    plan = json.loads(plan_file.read_text())
    assert planned["plan_digest"] == plan["plan_digest"]
    assert run("write", "validate", "--plan", str(plan_file))["plan_digest"] == plan["plan_digest"]
    common = ("--plan", str(plan_file), "--app", str(w01_runtime.app),
              "--model", str(w01_runtime.model), "--owner", identity["owner_uri"].rsplit("/p", 1)[1])
    apply = ("write", "apply", *common, "--reviewed-digest", plan["plan_digest"], "--apply")
    assert validate_result(plan, run(*apply))["classification"] == "applied"
    after = _snapshot(store)
    assert validate_result(plan, run(*apply))["classification"] == "noop"
    assert validate_result(plan, run("write", "recover", *common))["classification"] == "noop"
    assert _snapshot(store) == after
    entries = run("write", "journal")["entries"]
    assert len(entries) == 1 and entries[0]["state"] == "verified"
    backups = list((tmp_path / "journal/backups").rglob("*.sqlite"))
    assert len(backups) == 1
    assert backups[0].stat().st_mode & 0o777 == 0o600


def test_installed_client_refuses_absent_targets_before_journal_prepare(
    w01_runtime: W01Runtime, tmp_path: Path,
) -> None:
    configured = os.environ.get("MONEYWIZ_TEST_BUNDLE_PATH")
    if not configured:
        pytest.skip("set MONEYWIZ_TEST_BUNDLE_PATH for installed deletion evidence")
    launcher = Path(configured).resolve() / "Contents/Resources/runtime/moneywiz.sh"
    store, identity = _store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, store, identity, "w06-income")
    assert _classification(plan, _invoke(w01_runtime, store, plan)) == "applied"
    plan_file = tmp_path / "w06-absent-plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    environment = {**w01_runtime.environment, "MONEYWIZ_JOURNAL_DIR": str(tmp_path / "new-journal")}
    for variable in ("MONEYWIZ_TOOLS_HOST", "MONEYWIZ_CORE_DATA_WRITER"):
        environment.pop(variable, None)
    before = _snapshot(store)
    result = subprocess.run([
        str(launcher), "--db", str(store), "write", "apply", "--plan", str(plan_file),
        "--app", str(w01_runtime.app), "--model", str(w01_runtime.model),
        "--owner", identity["owner_uri"].rsplit("/p", 1)[1],
        "--reviewed-digest", plan["plan_digest"], "--apply",
    ], cwd=tmp_path, env=environment, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "exact target to exist before preparing a deletion" in result.stderr
    assert not list((tmp_path / "new-journal/entries").glob("*.json"))
    assert not list((tmp_path / "new-journal/backups").rglob("*.sqlite"))
    assert _snapshot(store) == before


@pytest.mark.parametrize("mutation", [
    "partial_proof", "missing_uri", "missing_account", "wrong_balance",
    "missing_holding", "wrong_units", "extra_field", "integer_verified",
])
def test_deletion_receipt_requires_complete_exact_proof(
    w01_runtime: W01Runtime, tmp_path: Path, mutation: str,
) -> None:
    store, identity = _store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, store, identity, "w06-buy", "w06-sell")
    applied = _invoke(w01_runtime, store, plan)
    assert applied.returncode == 0, applied.stderr
    receipt = json.loads(applied.stdout)
    validate_result(plan, receipt)
    postcondition = receipt["operations"][0]["postcondition"]
    if mutation == "partial_proof":
        receipt["operations"][0]["postcondition"] = {"retained_verified": True}
    elif mutation == "missing_uri":
        postcondition["deleted_object_uris"].pop()
    elif mutation == "missing_account":
        postcondition["accounts"] = []
    elif mutation == "wrong_balance":
        postcondition["accounts"][0]["balance"] = "999"
    elif mutation == "missing_holding":
        postcondition["holdings"] = []
    elif mutation == "wrong_units":
        postcondition["holdings"][0]["units"] = "999"
    elif mutation == "extra_field":
        postcondition["extra"] = "not in the reviewed postcondition"
    elif mutation == "integer_verified":
        postcondition["retained_verified"] = 1
    with pytest.raises(PlanValidationError):
        validate_result(plan, receipt)
