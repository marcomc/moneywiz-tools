"""Writer recovery must inspect durable state before any replay."""

from __future__ import annotations

import copy
import sqlite3

import pytest
import writer_client
from test_write_plan import plan
from write_journal import JournalPaths, JournalStore
from write_plan import validate_plan
from writer_client import WriterClient, WriterClientError


def receipt(payload, classification="applied"):
    operation = payload["operations"][0]
    return {
        "contract_version": 2,
        "plan_id": payload["plan_id"],
        "plan_digest": payload["plan_digest"],
        "classification": classification,
        "verified": classification in {"applied", "noop"},
        "operations": [
            {
                "operation_id": operation["operation_id"],
                "status": classification
                if classification in {"applied", "noop"}
                else "unknown",
                "transaction_entity": operation["transaction_entity"],
                "transaction_gid": operation["transaction_gid"],
                "durable_numeric_id": "1",
                "durable_uri": "x-coredata://store/WithdrawTransaction/p1",
                "new_payee_gid": operation["target_payee_gid"]
                if classification in {"applied", "noop"}
                else None,
            }
        ],
    }


@pytest.fixture
def execution(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(writer_client, "require_moneywiz_stopped", lambda: None)
    database = tmp_path / "synthetic.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE evidence(value TEXT)")
    payload = validate_plan(plan())
    journal = JournalStore(
        JournalPaths.from_environ({"MONEYWIZ_JOURNAL_DIR": str(tmp_path / "journal")})
    )
    client = WriterClient(tmp_path / "writer", tmp_path / "model", database)
    return client, payload, journal


def test_apply_requires_exact_reviewed_digest_before_preparing(execution):
    client, payload, journal = execution
    with pytest.raises(WriterClientError, match="reviewed-digest"):
        client.apply(payload, "0" * 64, journal)
    assert not list(journal.entries.iterdir())


def test_apply_retry_rechecks_persistence_without_replaying(execution, monkeypatch):
    client, payload, journal = execution
    calls = []

    def invoke(value, *, recover=False, lock_fd=None):
        calls.append(recover)
        assert lock_fd is not None
        return receipt(value, "noop" if recover else "applied")

    monkeypatch.setattr(client, "_invoke", invoke)
    client.apply(payload, payload["plan_digest"], journal)
    completed = journal.load("plan-1")["completed_at"]
    assert (
        client.apply(payload, payload["plan_digest"], journal)["classification"]
        == "noop"
    )
    assert calls == [False, True]
    assert journal.load("plan-1")["completed_at"] == completed


def test_unknown_after_lost_response_recovers_before_explicit_retry(
    execution, monkeypatch
):
    client, payload, journal = execution
    monkeypatch.setattr(
        client,
        "_invoke",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("response lost")),
    )
    with pytest.raises(WriterClientError, match="unknown"):
        client.apply(payload, payload["plan_digest"], journal)
    assert journal.load("plan-1")["state"] == "unresolved"
    calls = []

    def invoke(value, *, recover=False, lock_fd=None):
        calls.append(recover)
        return receipt(value, "retry_safe" if recover else "applied")

    monkeypatch.setattr(client, "_invoke", invoke)
    assert (
        client.apply(payload, payload["plan_digest"], journal)["classification"]
        == "applied"
    )
    assert calls == [True, False]


def test_previously_verified_then_reverted_state_cannot_replay(execution, monkeypatch):
    client, payload, journal = execution
    monkeypatch.setattr(client, "_invoke", lambda value, **_: receipt(value))
    client.apply(payload, payload["plan_digest"], journal)
    calls = []

    def reverted(value, *, recover=False, lock_fd=None):
        calls.append(recover)
        return receipt(value, "retry_safe")

    monkeypatch.setattr(client, "_invoke", reverted)
    assert client.recover(payload, journal)["classification"] == "unknown"
    with pytest.raises(WriterClientError, match="refusing replay"):
        client.apply(payload, payload["plan_digest"], journal)
    assert calls == [True, True]
    assert journal.load("plan-1")["ever_verified"] is True


def test_store_lock_covers_snapshot_and_receipt_without_blocking_sqlite(
    execution, monkeypatch
):
    client, payload, journal = execution
    original_prepare = journal.prepare

    def prepare(value, store):
        competitor = WriterClient(client.writer, client.model, store)
        with pytest.raises(WriterClientError, match="lock"), competitor._store_lock():
            pytest.fail("cooperating writer entered snapshot interval")
        return original_prepare(value, store)

    monkeypatch.setattr(journal, "prepare", prepare)
    monkeypatch.setattr(client, "_invoke", lambda value, **_: receipt(value))
    assert client.apply(payload, payload["plan_digest"], journal)["verified"]
    with sqlite3.connect(journal.load("plan-1")["backup"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM evidence").fetchone() == (0,)


@pytest.mark.parametrize(
    "damage",
    [
        "omitted",
        "duplicate",
        "wrong_gid",
        "wrong_store",
        "no_numeric_id",
        "false_verified",
    ],
)
def test_native_receipt_requires_complete_exact_operation_evidence(execution, damage):
    _client, payload, _journal = execution
    result = copy.deepcopy(receipt(payload))
    if damage == "omitted":
        result["operations"] = []
    elif damage == "duplicate":
        result["operations"] *= 2
    elif damage == "wrong_gid":
        result["operations"][0]["transaction_gid"] = "another-transaction"
    elif damage == "wrong_store":
        result["operations"][0]["durable_uri"] = (
            "x-coredata://another/WithdrawTransaction/p1"
        )
    elif damage == "no_numeric_id":
        result["operations"][0]["durable_numeric_id"] = ""
    else:
        result["verified"] = False
    with pytest.raises(WriterClientError):
        WriterClient._validate_result(payload, result)


def test_malformed_journal_is_never_treated_as_new_execution(execution, monkeypatch):
    client, payload, journal = execution
    (journal.entries / "plan-1.json").write_text("[]")
    monkeypatch.setattr(
        client,
        "_invoke",
        lambda *_args, **_kwargs: pytest.fail(
            "malformed evidence reached native mutation"
        ),
    )
    with pytest.raises(WriterClientError):
        client.apply(payload, payload["plan_digest"], journal)
