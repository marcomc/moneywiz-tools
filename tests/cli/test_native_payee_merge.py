"""W09 migrates the complete payee graph on marked disposable stores."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import writer_client
from test_native_transaction_create import W01Runtime, _crash, _invoke, w01_runtime
from write_journal import JournalPaths, JournalStore
from write_payees import build_merge_plan
from write_plan import validate_result
from writer_client import WriterClient, WriterClientError


def store(runtime: W01Runtime, directory: Path, flag: str = "--w09-exact") -> tuple[Path, dict]:
    path = directory / "w09-disposable.sqlite"
    result = subprocess.run(
        [str(runtime.fixture_builder), "--store", str(path), "--model",
         str(runtime.model), flag], cwd=directory, env=runtime.environment,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return path, json.loads(result.stdout)


def plan(runtime: W01Runtime, seeded: dict, *, fuzzy: bool = False) -> dict:
    inventory = {key: seeded[key] for key in ("owner_uri", "source", "survivor", "references")}
    approval = None
    if fuzzy:
        approval = {
            "user_id": int(seeded["owner_uri"].rsplit("/p", 1)[1]),
            "left_id": seeded["source"]["numeric_id"],
            "left_name": seeded["source"]["name"],
            "right_id": seeded["survivor"]["numeric_id"],
            "right_name": seeded["survivor"]["name"],
            "review_decision": "approved",
            "approved_canonical_id": seeded["survivor"]["numeric_id"],
            "review_notes": "Reviewed same merchant", "map_sha256": "a" * 64,
        }
    return build_merge_plan(
        inventory, store_uuid=seeded["store_uuid"], app_identity=runtime.app_identity,
        model_checksum="+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ=",
        kind="merge_approved_fuzzy_payee" if fuzzy else "merge_exact_payee",
        evidence_note="Synthetic approved pair", approval=approval,
    )


def inspect(runtime: W01Runtime, db: Path, directory: Path) -> dict:
    result = subprocess.run(
        [str(runtime.fixture_builder), "--inspect-w09", "--store", str(db),
         "--model", str(runtime.model)], cwd=directory, env=runtime.environment,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("fuzzy,flag", [
    (False, "--w09-exact"), (False, "--w09-untrimmed"), (True, "--w09-fuzzy"),
])
def test_w09_applies_replays_and_recovers_all_relationships(
    w01_runtime: W01Runtime, tmp_path: Path, fuzzy: bool, flag: str
) -> None:
    db, seeded = store(w01_runtime, tmp_path, flag)
    reviewed = plan(w01_runtime, seeded, fuzzy=fuzzy)
    before = _invoke(w01_runtime, db, reviewed, tmp_path, recover=True)
    assert before.returncode == 0, before.stderr
    assert validate_result(reviewed, json.loads(before.stdout))["classification"] == "retry_safe"
    applied = _invoke(w01_runtime, db, reviewed, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(reviewed, json.loads(applied.stdout))["classification"] == "applied"
    after = inspect(w01_runtime, db, tmp_path)
    assert after["source_absent"] is True
    assert after["card_payees"] == ["w09-survivor", "w09-unrelated"]
    assert after["unrelated_name"] == "Unrelated"
    for reference in seeded["references"]:
        assert reference["object_uri"] in after["survivor_references"][reference["relationship"]]
    for recover in (False, True):
        replay = _invoke(w01_runtime, db, reviewed, tmp_path, recover=recover)
        assert replay.returncode == 0, replay.stderr
        assert validate_result(reviewed, json.loads(replay.stdout))["classification"] == "noop"


def test_w09_refuses_unmarked_store_and_stale_inventory(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    db, seeded = store(w01_runtime, tmp_path, "--w09-unmarked")
    reviewed = plan(w01_runtime, seeded)
    refused = _invoke(w01_runtime, db, reviewed, tmp_path)
    assert refused.returncode == 2
    assert "marked disposable fixture required" in refused.stderr

    fresh_dir = tmp_path / "fresh"
    fresh_dir.mkdir()
    db, seeded = store(w01_runtime, fresh_dir)
    reviewed = plan(w01_runtime, seeded)
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE ZSYNCOBJECT SET ZNAME5 = 'Changed' WHERE ZGID = 'w09-source'")
    stale = _invoke(w01_runtime, db, reviewed, fresh_dir)
    assert stale.returncode == 2
    assert "stale" in stale.stderr or "changed" in stale.stderr


@pytest.mark.parametrize("boundary,expected", [
    ("--crash-before-save", "retry_safe"),
    ("--crash-after-save", "noop"),
])
def test_w09_crash_recovery(
    w01_runtime: W01Runtime, tmp_path: Path, boundary: str, expected: str
) -> None:
    db, seeded = store(w01_runtime, tmp_path)
    reviewed = plan(w01_runtime, seeded)
    crashed = _crash(w01_runtime, db, reviewed, tmp_path, boundary)
    assert crashed.returncode == (86 if boundary == "--crash-before-save" else 87)
    recovered = _invoke(w01_runtime, db, reviewed, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(reviewed, json.loads(recovered.stdout))["classification"] == expected


def test_w09_client_gate_precedes_journal(
    w01_runtime: W01Runtime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, seeded = store(w01_runtime, tmp_path, "--w09-unmarked")
    reviewed = plan(w01_runtime, seeded)
    monkeypatch.setenv("HOME", w01_runtime.environment["HOME"])
    monkeypatch.setattr(writer_client, "require_moneywiz_stopped", lambda: None)
    journal = JournalStore(JournalPaths.from_environ({
        "MONEYWIZ_JOURNAL_DIR": str(tmp_path / "journal"),
    }))
    client = WriterClient(w01_runtime.fixture_builder, w01_runtime.model, db)
    with pytest.raises(WriterClientError, match="disposable"):
        client.apply(reviewed, reviewed["plan_digest"], journal)
    assert not list(journal.entries.iterdir())
