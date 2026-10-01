"""Native W10 reassignment preserves linked transfer identity and recovers safely."""

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

import writer_client
from test_native_transaction_create import W01Runtime, w01_runtime
from test_transaction_create import request as envelope
from write_journal import JournalPaths, JournalStore
from write_plan import PlanValidationError, compute_digest, validate_plan, validate_result
from write_transactions import build_transfer_recipient_plan
from writer_client import WriterClient


def _fixture(runtime: W01Runtime, folder: Path, mode: str = "--w10-transfer-pair") -> tuple[Path, dict]:
    store = folder / "w10.sqlite"
    completed = subprocess.run(
        [str(runtime.fixture_builder), "--store", str(store), "--model", str(runtime.model), mode],
        capture_output=True, text=True, env=runtime.environment, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return store, json.loads(completed.stdout)


def _plan(runtime: W01Runtime, folder: Path, identity: dict) -> dict:
    value = envelope()
    value.update(
        plan_id="w10-plan",
        owner_uri=identity["owner_uri"],
        store_identity={"store_uuid": identity["store_uuid"]},
        app_identity=runtime.app_identity,
        expected_account_gid="w10-source",
        expected_cached_account_balance="700",
        currency_unit="GBP",
    )
    value["previous_destination_account"] = {
        "account_gid": "w10-previous", "currency_unit": "GBP",
        "expected_cached_balance": "350",
    }
    value["destination_account"] = {
        "account_gid": "w10-destination", "currency_unit": "GBP",
        "expected_cached_balance": "20",
    }
    value["operation"] = {
        "operation_id": "w10-reassign",
        "kind": "reassign_transfer_recipient",
        "expected_pair": identity["expected_pair"],
    }
    plan = build_transfer_recipient_plan(value)
    (folder / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return plan


def _run(runtime: W01Runtime, folder: Path, store: Path, *, recover: bool = False,
         crash: str | None = None) -> subprocess.CompletedProcess[str]:
    environment = dict(runtime.environment)
    if crash:
        environment["MONEYWIZ_TEST_CRASH_POINT"] = crash
    return subprocess.run(
        [str(runtime.fixture_builder), "--coredata-recover" if recover else "--coredata-write",
         "--store", str(store), "--model", str(runtime.model), "--plan", str(folder / "plan.json")],
        capture_output=True, text=True, env=environment, check=False,
    )


def _transfer_rows(store: Path) -> dict[str, tuple[str, str | None]]:
    with sqlite3.connect(f"file:{store}?mode=ro", uri=True) as connection:
        return {
            gid: (entity, account_gid)
            for gid, entity, account_gid in connection.execute(
                """SELECT row.ZGID, entity.Z_NAME, account.ZGID
                   FROM ZSYNCOBJECT AS row
                   JOIN Z_PRIMARYKEY AS entity ON entity.Z_ENT = row.Z_ENT
                   LEFT JOIN ZSYNCOBJECT AS account ON account.Z_PK = COALESCE(row.ZACCOUNT2, row.ZACCOUNT)
                   WHERE row.ZGID IN ('w10-sender', 'w10-recipient')"""
            )
        }


def test_native_transfer_recipient_reassignment_preserves_pair_and_replays(
    w01_runtime: W01Runtime, tmp_path: Path,
) -> None:
    store, identity = _fixture(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, tmp_path, identity)
    initial = _run(w01_runtime, tmp_path, store, recover=True)
    assert initial.returncode == 0, initial.stderr
    assert validate_result(plan, json.loads(initial.stdout))["classification"] == "retry_safe"

    applied = _run(w01_runtime, tmp_path, store)
    assert applied.returncode == 0, applied.stderr
    receipt = validate_result(plan, json.loads(applied.stdout))
    assert receipt["classification"] == "applied"
    assert receipt["operations"][0]["transfer_recipient_edit_details"]["reciprocal_links_verified"] is True
    assert _transfer_rows(store) == {
        "w10-sender": ("TransferWithdrawTransaction", "w10-source"),
        "w10-recipient": ("TransferDepositTransaction", "w10-destination"),
    }

    recovered = _run(w01_runtime, tmp_path, store, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(plan, json.loads(recovered.stdout))["classification"] == "noop"


@pytest.mark.parametrize(("crash", "code", "classification"), [
    ("before-save", 86, "retry_safe"),
    ("after-save", 87, "noop"),
])
def test_native_transfer_recipient_crash_recovery(
    w01_runtime: W01Runtime, tmp_path: Path, crash: str, code: int, classification: str,
) -> None:
    store, identity = _fixture(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, tmp_path, identity)
    crashed = _run(w01_runtime, tmp_path, store, crash=crash)
    assert crashed.returncode == code, crashed.stderr
    recovered = _run(w01_runtime, tmp_path, store, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(plan, json.loads(recovered.stdout))["classification"] == classification


def test_native_transfer_recipient_refuses_unmarked_store(
    w01_runtime: W01Runtime, tmp_path: Path,
) -> None:
    store, identity = _fixture(w01_runtime, tmp_path, "--w10-unmarked")
    _plan(w01_runtime, tmp_path, identity)
    attempted = _run(w01_runtime, tmp_path, store)
    assert attempted.returncode == 2
    assert "marked disposable fixture required" in attempted.stderr
    assert _transfer_rows(store)["w10-recipient"][1] == "w10-previous"


@pytest.mark.parametrize(("leg", "field", "value"), [
    ("sender", "exchange_rate", "0"),
    ("sender", "exchange_rate", "-1"),
    ("sender", "fee", "-1"),
    ("recipient", "original_fee", "-1"),
])
def test_native_transfer_recipient_rejects_invalid_rate_or_fee_even_with_valid_digest(
    w01_runtime: W01Runtime, tmp_path: Path, leg: str, field: str, value: str,
) -> None:
    store, identity = _fixture(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, tmp_path, identity)
    malformed = deepcopy(plan)
    expected_pair = malformed["operations"][0]["expected_pair"]
    if field == "exchange_rate":
        expected_pair["sender"][field] = value
        expected_pair["recipient"][field] = value
    else:
        expected_pair[leg][field] = value
    malformed["plan_digest"] = compute_digest(malformed)
    (tmp_path / "plan.json").write_text(json.dumps(malformed), encoding="utf-8")

    with pytest.raises(PlanValidationError, match="invalid rate or fee"):
        validate_plan(malformed)
    attempted = _run(w01_runtime, tmp_path, store)

    assert attempted.returncode == 2
    assert "invalid rate or fee" in attempted.stderr
    assert _transfer_rows(store)["w10-recipient"][1] == "w10-previous"


def test_writer_client_journals_and_recovers_transfer_recipient(
    w01_runtime: W01Runtime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, identity = _fixture(w01_runtime, tmp_path)
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
