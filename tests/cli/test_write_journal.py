from __future__ import annotations

import sqlite3
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import pytest
from test_write_plan import plan as sample_plan
from test_writer_client import receipt
from write_journal import JournalError, JournalPaths, JournalStore
from write_plan import validate_plan


def valid_plan(plan_id):
    value = sample_plan()
    value["plan_id"] = plan_id
    value["source_event_id"] = plan_id
    value["operations"][0]["source_event_id"] = plan_id
    return validate_plan(value)


def test_prepared_journal_has_private_consistent_backup(tmp_path: Path) -> None:
    store_path = tmp_path / "synthetic.sqlite"
    with sqlite3.connect(store_path) as connection:
        connection.execute("CREATE TABLE evidence(value TEXT)")
        connection.execute("INSERT INTO evidence VALUES ('before')")
    paths = JournalPaths.from_environ(
        {"MONEYWIZ_JOURNAL_DIR": str(tmp_path / "private")}
    )
    journal = JournalStore(paths)
    journal.prepare({"plan_id": "p1", "plan_digest": "a" * 64}, store_path)
    record = journal.load("p1")
    assert record["state"] == "prepared"
    assert stat.S_IMODE(Path(record["backup"]).stat().st_mode) == 0o600
    with sqlite3.connect(record["backup"]) as backup:
        assert backup.execute("SELECT value FROM evidence").fetchone() == ("before",)


def test_snapshot_handles_sqlite_paths_containing_uri_characters(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "synthetic #?.sqlite"
    with sqlite3.connect(store_path) as connection:
        connection.execute("CREATE TABLE evidence(value TEXT)")
    journal = JournalStore(
        JournalPaths.from_environ({"MONEYWIZ_JOURNAL_DIR": str(tmp_path / "private")})
    )
    assert (
        journal.prepare({"plan_id": "escaped", "plan_digest": "a" * 64}, store_path)[
            "state"
        ]
        == "prepared"
    )


def test_cleanup_keeps_unresolved_and_applies_verified_retention(
    tmp_path: Path,
) -> None:
    database = tmp_path / "synthetic.sqlite"
    sqlite3.connect(database).close()
    journal = JournalStore(
        JournalPaths.from_environ({"MONEYWIZ_JOURNAL_DIR": str(tmp_path / "private")})
    )
    plan = valid_plan("old")
    journal.prepare(plan, database)
    journal.record_result("old", receipt(valid_plan("old")))
    record = journal.load("old")
    record["completed_at"] = (datetime.now(UTC) - timedelta(days=91)).isoformat()
    from write_journal import _write_json

    _write_json(journal.entries / "old.json", record)
    assert journal.cleanup(apply=False)["eligible"][0]["plan_id"] == "old"
    assert journal.cleanup(apply=True)["deleted"] == ["old"]
    assert Path(record["backup"]).exists()


def test_source_event_cannot_be_reused_with_a_different_reviewed_plan(
    tmp_path: Path,
) -> None:
    database = tmp_path / "synthetic.sqlite"
    sqlite3.connect(database).close()
    journal = JournalStore(
        JournalPaths.from_environ({"MONEYWIZ_JOURNAL_DIR": str(tmp_path / "private")})
    )
    first = {
        "plan_id": "first",
        "plan_digest": "a" * 64,
        "store_identity": {"store_uuid": "store"},
        "owner_uri": "owner",
        "source_event_id": "event",
    }
    second = {**first, "plan_id": "second", "plan_digest": "b" * 64}
    journal.prepare(first, database)
    with pytest.raises(JournalError, match="already reserved"):
        journal.prepare(second, database)


def test_discovery_does_not_create_private_directories(tmp_path: Path) -> None:
    root = tmp_path / "does-not-exist"
    paths = JournalPaths.from_environ({"MONEYWIZ_JOURNAL_DIR": str(root)})
    journal = JournalStore(paths, create=False)
    assert journal.locations()["journal_root"] == str(root)
    assert not root.exists()


def test_cleanup_does_not_follow_unmanaged_backup_path(tmp_path: Path) -> None:
    database = tmp_path / "synthetic.sqlite"
    sqlite3.connect(database).close()
    journal = JournalStore(
        JournalPaths.from_environ({"MONEYWIZ_JOURNAL_DIR": str(tmp_path / "private")})
    )
    journal.prepare(valid_plan("unsafe"), database)
    journal.record_result("unsafe", receipt(valid_plan("unsafe")))
    record = journal.load("unsafe")
    record["completed_at"] = (datetime.now(UTC) - timedelta(days=91)).isoformat()
    outside = tmp_path / "must-not-delete.sqlite"
    outside.touch()
    record["backup"] = str(outside)
    from write_journal import _write_json

    _write_json(journal.entries / "unsafe.json", record)
    assert journal.cleanup(apply=True)["deleted"] == ["unsafe"]
    assert outside.exists()


def test_cleanup_retains_malformed_or_referenced_evidence(tmp_path: Path) -> None:
    from write_journal import _write_json

    database = tmp_path / "store.sqlite"
    sqlite3.connect(database).close()
    journal = JournalStore(JournalPaths(tmp_path / "journal", None))
    journal.prepare(valid_plan("old"), database)
    journal.record_result("old", receipt(valid_plan("old"), "noop"))
    old = journal.load("old")
    old["completed_at"] = (datetime.now(UTC) - timedelta(days=91)).isoformat()
    _write_json(journal.entries / "old.json", old)
    journal.prepare(
        {"plan_id": "pending", "plan_digest": "b" * 64, "source_event_id": "pending"},
        database,
    )
    pending = journal.load("pending")
    pending["references"] = ["old"]
    _write_json(journal.entries / "pending.json", pending)
    assert journal.cleanup(apply=True)["deleted"] == []
    (journal.entries / "pending.json").write_text("[]")
    assert journal.cleanup(apply=True)["deleted"] == []
    assert (journal.entries / "old.json").exists()


def test_cleanup_refuses_active_store_writer_and_preserves_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    from write_journal import _write_json, store_lock

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    database = tmp_path / "store.sqlite"
    sqlite3.connect(database).close()
    journal = JournalStore(JournalPaths(tmp_path / "journal", None))
    journal.prepare(valid_plan("old"), database)
    journal.record_result("old", receipt(valid_plan("old"), "noop"))
    record = journal.load("old")
    record["completed_at"] = (datetime.now(UTC) - timedelta(days=91)).isoformat()
    _write_json(journal.entries / "old.json", record)
    with store_lock(database), pytest.raises(JournalError, match="lock"):
        journal.cleanup(apply=True)
    assert journal.load("old")["state"] == "verified"
    assert Path(record["backup"]).exists()


@pytest.mark.parametrize("damage", ["plan", "receipt", "digest", "identity"])
def test_cleanup_retains_incomplete_verified_evidence(
    tmp_path: Path, damage: str
) -> None:
    from write_journal import _write_json

    database = tmp_path / "store.sqlite"
    sqlite3.connect(database).close()
    journal = JournalStore(JournalPaths(tmp_path / "journal", None))
    plan = valid_plan("old")
    journal.prepare(plan, database)
    journal.record_result("old", receipt(plan))
    record = journal.load("old")
    record["completed_at"] = (datetime.now(UTC) - timedelta(days=91)).isoformat()
    if damage == "plan":
        record["plan"] = {"plan_id": "old"}
    elif damage == "receipt":
        record["result"]["operations"] = []
    elif damage == "digest":
        record["result"]["plan_digest"] = "0" * 64
    else:
        record["result"]["operations"][0]["durable_uri"] = (
            "x-coredata://other/Transaction/p1"
        )
    _write_json(journal.entries / "old.json", record)
    assert journal.cleanup(apply=True)["deleted"] == []
    assert journal.load("old")["state"] == "verified"
