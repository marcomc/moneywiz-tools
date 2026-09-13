"""Read-contract tests use only synthetic rows, never production database defaults."""

import importlib
import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def reads(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("read_support")


@pytest.fixture
def snapshots(reads):
    return importlib.import_module("snapshot")


def test_apple_epoch_is_absolute(reads):
    row = SimpleNamespace(_raw={"ZDATE1": 0})
    assert reads.transaction_time(row) == datetime(2001, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize("value", [None, True, "0", float("nan"), float("inf")])
def test_invalid_timestamp_is_not_a_silent_missing_row(reads, value):
    with pytest.raises((TypeError, ValueError)):
        reads.transaction_time(SimpleNamespace(_raw={"ZDATE1": value}))


def test_until_whole_day_includes_dst_short_day(reads):
    end, exclusive = reads.cutoff("2026-03-29", "Europe/Rome")
    assert exclusive
    assert end == datetime(2026, 3, 29, 22, tzinfo=UTC)
    previous, _ = reads.cutoff("2026-03-28", "Europe/Rome")
    assert (end - previous).total_seconds() == 23 * 3600


def test_until_whole_day_includes_dst_long_day(reads):
    end, _ = reads.cutoff("2026-10-25", "Europe/Rome")
    previous, _ = reads.cutoff("2026-10-24", "Europe/Rome")
    assert (end - previous).total_seconds() == 25 * 3600


def test_timestamp_requires_explicit_offset(reads):
    with pytest.raises(ValueError, match="explicit UTC offset"):
        reads.cutoff("2026-10-25T02:30:00", "Europe/Rome")
    first, _ = reads.cutoff("2026-10-25T02:30:00+02:00")
    second, _ = reads.cutoff("2026-10-25T02:30:00+01:00")
    assert (second - first).total_seconds() == 3600


def test_midnight_boundary_and_account_scope(reads):
    boundary, _ = reads.cutoff("2026-09-12")
    seconds = (boundary - reads.APPLE_EPOCH).total_seconds()
    rows = {
        n: SimpleNamespace(id=n, account=account, _raw={"ZDATE1": seconds + offset})
        for n, account, offset in [(1, 10, -1), (2, 10, 0), (3, 20, -1)]
    }
    api = SimpleNamespace(transaction_manager=SimpleNamespace(records=lambda: rows))
    assert [
        row.id for row in reads.selected_transactions(api, 10, "2026-09-12", "UTC")
    ] == [1]


def test_snapshot_selection_preserves_accountless_budget_rows(reads):
    account_transaction = SimpleNamespace(id=1, account=10, _raw={"ZDATE1": 0})
    budget_transaction = SimpleNamespace(id=2, _raw={"ZDATE1": 1})
    api = SimpleNamespace(
        transaction_manager=SimpleNamespace(
            records=lambda: {1: account_transaction, 2: budget_transaction}
        )
    )

    assert [row.id for row in reads.selected_transactions(api, None, None, "UTC")] == [
        1
    ]
    assert [
        row.id for row in reads.selected_snapshot_transactions(api, None, None, "UTC")
    ] == [1, 2]
    assert [
        row.id for row in reads.selected_snapshot_transactions(api, 10, None, "UTC")
    ] == [1]


def test_partial_read_emits_explicit_diagnostic(reads, capsys):
    report = {
        "complete": False,
        "managers": {
            "accounts": {
                "source_count": 2,
                "parsed_count": 1,
                "skipped": [{"record_id": 12}],
            }
        },
    }
    api = SimpleNamespace(completeness=lambda: SimpleNamespace(as_dict=lambda: report))
    actual, code = reads.report_completeness(api)
    assert code == 3
    assert actual == report
    assert json.loads(capsys.readouterr().err)["read_completeness"] == report


def test_read_failure_does_not_leak_row_values(reads, capsys):
    def failed():
        raise ValueError("private financial payload")

    assert reads.run_read_command(failed) == 2
    output = capsys.readouterr().err
    assert "private financial payload" not in output
    assert json.loads(output)["error"] == "ValueError"


def transfer_rows():
    return [
        {
            "id": 1,
            "account": 10,
            "entity": "TransferWithdrawTransaction",
            "recipient_account": 20,
            "recipient_transaction": 2,
            "reconciled": True,
            "datetime": "2026-09-12T00:00:00+00:00",
            "amount": "-10",
        },
        {
            "id": 2,
            "account": 20,
            "entity": "TransferDepositTransaction",
            "sender_account": 10,
            "sender_transaction": 1,
            "reconciled": True,
            "datetime": "2026-09-12T00:00:00+00:00",
            "amount": "12",
        },
    ]


def test_graph_checks_reciprocal_accounts_and_owners(snapshots):
    accounts = [{"id": 10, "user": 4}, {"id": 20, "user": 4}]
    rows = transfer_rows()
    assert snapshots.audit_graph(accounts, rows) == []
    rows[1]["sender_account"] = 999
    assert any(
        item["kind"] == "nonreciprocal_transfer"
        for item in snapshots.audit_graph(accounts, rows)
    )
    rows[1]["sender_account"] = 10
    accounts[1]["user"] = 5
    assert any(
        item["kind"] == "cross_owner_transfer"
        for item in snapshots.audit_graph(accounts, rows)
    )


def test_graph_reports_missing_leg_and_unreconciled_pair(snapshots):
    accounts = [{"id": 10, "user": 4}, {"id": 20, "user": 4}]
    rows = transfer_rows()
    assert (
        snapshots.audit_graph(accounts, rows[:1])[0]["kind"] == "missing_transfer_leg"
    )
    rows[1]["reconciled"] = False
    assert (
        snapshots.audit_graph(accounts, rows)[0]["kind"] == "unreconciled_transfer_legs"
    )


def test_duplicate_amount_date_is_only_a_candidate(snapshots):
    rows = [
        {
            "id": n,
            "account": 10,
            "entity": "DepositTransaction",
            "amount": "1",
            "datetime": "2026-09-12T00:00:00Z",
            "description": "Synthetic refund",
        }
        for n in (1, 2)
    ]
    assert snapshots.audit_graph([{"id": 10, "user": 4}], rows) == [
        {"kind": "coincident_transactions", "severity": "candidate", "ids": [1, 2]}
    ]


def test_accountless_budget_transaction_is_not_a_missing_account(snapshots):
    rows = [
        {
            "id": 1,
            "entity": "TransferBudgetTransaction",
            "amount": "1",
            "datetime": "2026-09-12T00:00:00Z",
            "description": "Synthetic budget transfer",
        }
    ]

    assert snapshots.audit_graph([], rows) == []


def test_graph_audit_rejects_non_scalar_candidate_values(snapshots):
    rows = [
        {
            "id": 1,
            "account": 10,
            "entity": "DepositTransaction",
            "amount": "1",
            "datetime": "2026-09-12T00:00:00Z",
            "description": {"binary_bytes": 2},
        }
    ]

    with pytest.raises(TypeError, match="non-scalar"):
        snapshots.audit_graph([{"id": 10, "user": 4}], rows)


def test_snapshot_entrypoint_complete_and_partial(reads, synthetic_store):
    script = Path(__file__).resolve().parents[2] / "scripts/snapshot.py"
    command = [
        sys.executable,
        str(script),
        "--db",
        str(synthetic_store),
        "--until",
        "2001-01-02",
    ]
    complete = subprocess.run(command, capture_output=True, text=True, check=False)
    assert complete.returncode == 0, complete.stderr
    payload = json.loads(complete.stdout)
    assert payload["completeness"]["complete"] is True
    assert payload["transactions"][0]["id"] == 11
    assert payload["transactions"][0]["datetime"] == "2001-01-01T00:01:40+00:00"
    assert payload["accounts"][0]["recorded_balance"] == "2.0"
    assert payload["source_coverage"] == "not_verified"
    assert payload["audit"] == []
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(
            "UPDATE ZSYNCOBJECT SET ZORIGINALAMOUNT = NULL WHERE Z_PK = 11"
        )
    partial = subprocess.run(command, capture_output=True, text=True, check=False)
    assert partial.returncode == 3, partial.stderr
    result = json.loads(partial.stdout)
    assert result["transactions"] == []
    report = result["completeness"]["managers"]["transactions"]
    assert report["source_count"] == 1
    assert report["parsed_count"] == 0
    assert report["skipped"][0]["record_id"] == 11


@pytest.mark.parametrize(
    "command,args,rows_key",
    [
        ("snapshot", [], "transactions"),
        ("transactions", ["--format", "json", "--diagnostics"], "rows"),
    ],
)
@pytest.mark.parametrize(
    "column,value,unsafe_text",
    [
        pytest.param(
            "ZACCOUNT2", "unsafe-account-id", "unsafe-account-id", id="account-text"
        ),
        pytest.param(
            "ZGID",
            sqlite3.Binary(b"unsafe-gid-payload"),
            "unsafe-gid-payload",
            id="gid-blob",
        ),
        pytest.param("ZRECONCILED", None, None, id="reconciled-null"),
        pytest.param("ZRECONCILED", 2, None, id="reconciled-nonboolean-integer"),
        pytest.param(
            "ZRECONCILED",
            "unsafe-reconciled-value",
            "unsafe-reconciled-value",
            id="reconciled-text",
        ),
    ],
)
def test_malformed_transaction_identity_and_reconciled_are_safe_partial_reads(
    reads,
    synthetic_store,
    command,
    args,
    rows_key,
    column,
    value,
    unsafe_text,
):
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(
            f"UPDATE ZSYNCOBJECT SET {column} = ? WHERE Z_PK = 11", (value,)
        )
    script = Path(__file__).resolve().parents[2] / "scripts" / f"{command}.py"
    result = subprocess.run(
        [sys.executable, str(script), "--db", str(synthetic_store), *args],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 3, result.stderr
    payload = json.loads(result.stdout)
    assert payload[rows_key] == []
    completeness = payload["completeness"]
    assert completeness["complete"] is False
    report = completeness["managers"]["transactions"]
    assert report["source_count"] == 1
    assert report["parsed_count"] == 0
    assert report["skipped"][0]["record_id"] == 11
    rendered = result.stdout + result.stderr
    assert "Traceback" not in rendered
    if unsafe_text is not None:
        assert unsafe_text not in rendered
    assert "binary_bytes" not in rendered
    assert "BLOB(" not in rendered


def test_snapshot_preserves_parsed_accountless_budget_transaction(
    reads, synthetic_store
):
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(
            "INSERT INTO Z_PRIMARYKEY VALUES (44, 'TransferBudgetTransaction', 36)"
        )
        connection.execute(
            """
            INSERT INTO ZSYNCOBJECT
              (Z_PK,Z_ENT,ZOBJECTCREATIONDATE,ZGID,ZRECONCILED,ZAMOUNT1,ZDESC2,
               ZDATE1,ZSTATUS1,ZFLAGS1)
            VALUES (12,44,0,'synthetic-budget-transfer',0,1,
                    'Synthetic budget transfer',101,1,0)
            """
        )
    script = Path(__file__).resolve().parents[2] / "scripts/snapshot.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--db",
            str(synthetic_store),
            "--until",
            "2001-01-02",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["completeness"]["managers"]["transactions"]["parsed_ids"] == [
        11,
        12,
    ]
    assert [row["id"] for row in payload["transactions"]] == [11, 12]
    assert not any(item["kind"] == "missing_account" for item in payload["audit"])


def test_accounts_unfiltered_preserves_parsed_row_with_missing_user(
    reads, synthetic_store
):
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(
            """
            INSERT INTO ZSYNCOBJECT
              (Z_PK,Z_ENT,ZOBJECTCREATIONDATE,ZGID,ZDISPLAYORDER,ZGROUPID,ZNAME,
               ZCURRENCYNAME,ZOPENINGBALANCE,ZUSER,ZARCHIVED,ZBALLANCE)
            VALUES (12,12,0,'synthetic-orphan-owner',1,0,'Orphan owner account',
                    'EUR',0,99,0,0)
            """
        )
    script = Path(__file__).resolve().parents[2] / "scripts/accounts.py"

    def run(*extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(script),
                "--db",
                str(synthetic_store),
                "--format",
                "json",
                "--diagnostics",
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    unfiltered = run()
    assert unfiltered.returncode == 0, unfiltered.stderr
    payload = json.loads(unfiltered.stdout)
    assert payload["completeness"]["managers"]["accounts"]["parsed_ids"] == [10, 12]
    assert [(row["id"], row["user"]) for row in payload["rows"]] == [
        (10, 4),
        (12, 99),
    ]

    owner_filtered = run("--user", "99")
    assert owner_filtered.returncode == 0, owner_filtered.stderr
    assert [row["id"] for row in json.loads(owner_filtered.stdout)["rows"]] == [12]

    other_filtered = run("--user", "4")
    assert other_filtered.returncode == 0, other_filtered.stderr
    assert [row["id"] for row in json.loads(other_filtered.stdout)["rows"]] == [10]


def test_snapshot_blob_description_is_a_bounded_read_error(reads, synthetic_store):
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(
            "UPDATE ZSYNCOBJECT SET ZDESC2 = ? WHERE Z_PK = 11",
            (sqlite3.Binary(b"\x01\x02"),),
        )
    script = Path(__file__).resolve().parents[2] / "scripts/snapshot.py"
    result = subprocess.run(
        [sys.executable, str(script), "--db", str(synthetic_store)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error == {
        "status": "error",
        "error": "TypeError",
        "message": "Read failed; check database, schema and command arguments",
    }
    assert "Traceback" not in result.stderr
    assert "binary_bytes" not in result.stderr


@pytest.mark.parametrize("command", ["snapshot", "transactions"])
def test_extreme_date_is_a_bounded_read_error(reads, synthetic_store, command):
    script = Path(__file__).resolve().parents[2] / "scripts" / f"{command}.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--db",
            str(synthetic_store),
            "--until",
            "9999-12-31",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["error"] == "ValueError"
    assert error["message"] == (
        "Read failed; check database, schema and command arguments"
    )
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "command,args",
    [
        ("accounts", []),
        ("transactions", ["--until", "2001-01-02"]),
        ("holdings", ["--account", "10"]),
    ],
)
def test_list_entrypoints_expose_complete_diagnostics(
    reads, synthetic_store, command, args
):
    script = Path(__file__).resolve().parents[2] / "scripts" / f"{command}.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--db",
            str(synthetic_store),
            "--format",
            "json",
            "--diagnostics",
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["completeness"]["complete"] is True


@pytest.mark.parametrize(
    "command,args",
    [
        ("snapshot", ["--until", "2001-01-02"]),
        (
            "transactions",
            ["--until", "2001-01-02", "--format", "json", "--diagnostics"],
        ),
    ],
)
def test_partial_tag_metadata_is_not_silently_complete(
    reads, partial_metadata_store, command, args
):
    script = Path(__file__).resolve().parents[2] / "scripts" / f"{command}.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--db",
            str(partial_metadata_store),
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    completeness = payload["completeness"]
    assert completeness["complete"] is False
    transactions = completeness["managers"]["transactions"]
    assert transactions["source_count"] == 1
    assert transactions["parsed_count"] == 1
    relationship = transactions["relationships"]["transaction_tags"]
    assert relationship["status"] == "error"
    assert relationship["complete"] is False
    assert relationship["storage"] == "unknown"
    assert relationship["storage_name"] is None
    assert "Traceback" not in result.stderr


def test_missing_database_is_not_created(reads, tmp_path):
    store = tmp_path / "missing.sqlite"
    script = Path(__file__).resolve().parents[2] / "scripts/snapshot.py"
    result = subprocess.run(
        [sys.executable, str(script), "--db", str(store)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert not store.exists()
    assert "Traceback" not in result.stderr
