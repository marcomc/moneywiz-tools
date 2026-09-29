"""Native W07 replacement and crash recovery on disposable model-48 stores."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import writer_client
from test_native_transaction_create import W01Runtime, w01_runtime
from test_transfer_plan import request as transfer_request
from write_journal import JournalPaths, JournalStore
from write_plan import validate_result
from write_transactions import build_transfer_plan
from writer_client import WriterClient


def _fixture(runtime: W01Runtime, folder: Path, mode: str) -> tuple[Path, dict]:
    store = folder / "w07.sqlite"
    completed = subprocess.run(
        [str(runtime.fixture_builder), "--store", str(store), "--model",
         str(runtime.model), mode],
        capture_output=True, text=True, env=runtime.environment, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return store, json.loads(completed.stdout)


def _plan(runtime: W01Runtime, folder: Path, identity: dict,
          *, paired: bool = False, reverse: bool = False) -> dict:
    value = transfer_request(paired=paired, reverse=reverse)
    value["plan_id"] = "w07-plan"
    value["store_identity"] = {"store_uuid": identity["store_uuid"]}
    value["owner_uri"] = identity["owner_uri"]
    value["app_identity"] = runtime.app_identity
    value["expected_account_gid"] = "w07-source"
    value["expected_cached_account_balance"] = "80"
    value["destination_account"]["account_gid"] = "w07-destination"
    value["destination_account"]["expected_cached_balance"] = "73" if paired else "50"
    old = value["operation"]["source_old"]
    old["transaction_gid"] = "w07-import-source"
    old["transaction_numeric_id"] = identity["source_numeric_id"]
    old["account_gid"] = "w07-source"
    old["payee_gid"] = "w07-payee"
    old["tag_gids"] = ["w07-tag"]
    old["category_assignment_uris"] = [identity["source_assignment_uri"]]
    if paired:
        destination = value["operation"]["destination_old"]
        destination["transaction_gid"] = "w07-import-destination"
        destination["transaction_numeric_id"] = identity["destination_numeric_id"]
        destination["account_gid"] = "w07-destination"
        destination["occurred_at"] = value["operation"]["receive_at"]
    plan = build_transfer_plan(value)
    (folder / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return plan


def _run(runtime: W01Runtime, folder: Path, store: Path, *, recover: bool = False,
         crash: str | None = None, production: bool = False) -> subprocess.CompletedProcess[str]:
    environment = dict(runtime.environment)
    if crash:
        environment["MONEYWIZ_TEST_CRASH_POINT"] = crash
    return subprocess.run(
        [str(runtime.host if production else runtime.fixture_builder),
         "--coredata-recover" if recover else "--coredata-write",
         "--store", str(store), "--model", str(runtime.model),
         "--plan", str(folder / "plan.json")],
        capture_output=True, text=True, env=environment, check=False,
    )


def _gids(store: Path) -> set[str]:
    with sqlite3.connect(f"file:{store}?mode=ro", uri=True) as connection:
        return {row[0] for row in connection.execute(
            "SELECT ZGID FROM ZSYNCOBJECT WHERE ZGID IS NOT NULL"
        )}


@pytest.mark.parametrize("mode,paired,reverse", [
    ("--w07-source", False, False),
    ("--w07-paired", True, False),
    ("--w07-reverse", False, True),
])
def test_native_transfer_replaces_old_rows_atomically(
    w01_runtime: W01Runtime, tmp_path: Path, mode: str, paired: bool, reverse: bool
) -> None:
    store, identity = _fixture(w01_runtime, tmp_path, mode)
    plan = _plan(w01_runtime, tmp_path, identity, paired=paired, reverse=reverse)
    initial = _run(w01_runtime, tmp_path, store, recover=True)
    assert initial.returncode == 0, initial.stderr
    assert validate_result(plan, json.loads(initial.stdout))["classification"] == "retry_safe"
    applied = _run(w01_runtime, tmp_path, store)
    assert applied.returncode == 0, applied.stderr
    receipt = validate_result(plan, json.loads(applied.stdout))
    assert receipt["classification"] == "applied"
    assert receipt["operations"][0]["transfer_details"]["reciprocal_links_verified"] is True
    recovered = _run(w01_runtime, tmp_path, store, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(plan, json.loads(recovered.stdout))["classification"] == "noop"
    gids = _gids(store)
    assert "w07-import-source" not in gids
    if paired:
        assert "w07-import-destination" not in gids
    assert plan["operations"][0]["transaction_gid"] in gids
    assert plan["operations"][0]["recipient_transaction_gid"] in gids
    with sqlite3.connect(f"file:{store}?mode=ro", uri=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ZCATEGORYASSIGMENT").fetchone()[0] == 0


@pytest.mark.parametrize("crash,code,classification", [
    ("before-save", 86, "retry_safe"),
    ("after-save", 87, "noop"),
])
def test_native_transfer_crash_recovery(
    w01_runtime: W01Runtime, tmp_path: Path, crash: str, code: int,
    classification: str,
) -> None:
    store, identity = _fixture(w01_runtime, tmp_path, "--w07-source")
    plan = _plan(w01_runtime, tmp_path, identity)
    crashed = _run(w01_runtime, tmp_path, store, crash=crash)
    assert crashed.returncode == code, crashed.stderr
    recovered = _run(w01_runtime, tmp_path, store, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(plan, json.loads(recovered.stdout))["classification"] == classification


def test_native_transfer_refuses_ambiguous_counterpart(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _fixture(w01_runtime, tmp_path, "--w07-ambiguous")
    _plan(w01_runtime, tmp_path, identity)
    original = _gids(store)
    attempted = _run(w01_runtime, tmp_path, store)
    assert attempted.returncode == 2
    assert "ambiguous imported counterpart" in attempted.stderr
    assert _gids(store) == original


def test_native_transfer_refuses_voided_import(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _fixture(w01_runtime, tmp_path, "--w07-voided")
    _plan(w01_runtime, tmp_path, identity)
    original = _gids(store)
    attempted = _run(w01_runtime, tmp_path, store)
    assert attempted.returncode == 2
    assert "unsupported links" in attempted.stderr
    assert _gids(store) == original


@pytest.mark.parametrize("missing_leg", ["transaction_gid", "recipient_transaction_gid"])
def test_native_transfer_refuses_partial_pair(
    w01_runtime: W01Runtime, tmp_path: Path, missing_leg: str
) -> None:
    store, identity = _fixture(w01_runtime, tmp_path, "--w07-source")
    plan = _plan(w01_runtime, tmp_path, identity)
    applied = _run(w01_runtime, tmp_path, store)
    assert applied.returncode == 0, applied.stderr
    with sqlite3.connect(store) as connection:
        connection.execute(
            "DELETE FROM ZSYNCOBJECT WHERE ZGID = ?",
            (plan["operations"][0][missing_leg],),
        )
    partial = _gids(store)
    recovered = _run(w01_runtime, tmp_path, store, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(plan, json.loads(recovered.stdout))["classification"] == "unknown"
    assert _gids(store) == partial


def test_native_transfer_refuses_unmarked_store(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _fixture(w01_runtime, tmp_path, "--w07-unmarked")
    _plan(w01_runtime, tmp_path, identity)
    attempted = _run(w01_runtime, tmp_path, store)
    assert attempted.returncode == 2
    assert "marked disposable fixture required" in attempted.stderr
    inspection = _run(w01_runtime, tmp_path, store, recover=True)
    assert inspection.returncode == 2
    assert "marked disposable fixture required" in inspection.stderr


def test_production_host_writes_disposable_transfer(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    active = subprocess.run(["pgrep", "-x", "MoneyWiz"], capture_output=True,
                            text=True, check=False)
    if active.returncode == 0:
        pytest.skip("MoneyWiz is running; production host requires it to be closed")
    assert active.returncode == 1
    store, identity = _fixture(w01_runtime, tmp_path, "--w07-source")
    plan = _plan(w01_runtime, tmp_path, identity)
    applied = _run(w01_runtime, tmp_path, store, production=True)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(plan, json.loads(applied.stdout))["classification"] == "applied"
    recovered = _run(w01_runtime, tmp_path, store, recover=True, production=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(plan, json.loads(recovered.stdout))["classification"] == "noop"


def test_native_transfer_rejects_stale_imported_row(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _fixture(w01_runtime, tmp_path, "--w07-source")
    plan = _plan(w01_runtime, tmp_path, identity)
    original = _gids(store)
    plan.pop("plan_digest")
    plan["operations"][0]["source_old"]["note"] = "stale note"
    from write_plan import validate_plan
    plan = validate_plan(plan)
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    attempted = _run(w01_runtime, tmp_path, store)
    assert attempted.returncode == 2
    assert "reviewed identity" in attempted.stderr
    assert _gids(store) == original


def test_writer_client_journals_and_recovers_transfer(
    w01_runtime: W01Runtime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, identity = _fixture(w01_runtime, tmp_path, "--w07-source")
    plan = _plan(w01_runtime, tmp_path, identity)
    monkeypatch.setenv("HOME", w01_runtime.environment["HOME"])
    monkeypatch.setattr(writer_client, "require_moneywiz_stopped", lambda: None)
    journal = JournalStore(JournalPaths.from_environ({
        "MONEYWIZ_JOURNAL_DIR": str(tmp_path / "journal"),
    }))
    client = WriterClient(w01_runtime.fixture_builder, w01_runtime.model, store)
    applied = client.apply(plan, plan["plan_digest"], journal)
    assert applied["classification"] == "applied"
    assert client.apply(plan, plan["plan_digest"], journal)["classification"] == "noop"
    assert client.recover(plan, journal)["classification"] == "noop"
