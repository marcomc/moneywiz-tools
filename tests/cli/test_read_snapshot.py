"""Read-contract tests use only synthetic rows, never production database defaults."""

import importlib
import json
import sqlite3
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
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


PAIR_FINDINGS = {
    "cross_owner_transfer",
    "different_transfer_dates",
    "unreconciled_transfer_legs",
}


def finding_kinds(findings):
    return [finding["kind"] for finding in findings]


@pytest.mark.parametrize(
    "reverse", [False, True], ids=["withdrawal-first", "deposit-first"]
)
def test_graph_emits_one_cross_owner_observation_per_reciprocal_pair(
    snapshots, reverse
):
    accounts = [{"id": 10, "user": 4}, {"id": 20, "user": 5}]
    rows = transfer_rows()
    if reverse:
        rows.reverse()

    findings = snapshots.audit_graph(accounts, rows)

    assert findings == [{"kind": "cross_owner_transfer", "ids": [1, 2]}]


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
    assert snapshots.audit_graph(accounts, rows) == [
        {"kind": "cross_owner_transfer", "ids": [1, 2]}
    ]


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


@pytest.mark.parametrize(
    "different_date,reconciled,owners,expected",
    [
        (False, (True, True), (4, 4), []),
        (True, (True, True), (4, 4), ["different_transfer_dates"]),
        (False, (False, True), (4, 4), ["unreconciled_transfer_legs"]),
        (False, (True, False), (4, 4), ["unreconciled_transfer_legs"]),
        (False, (False, False), (4, 4), ["unreconciled_transfer_legs"]),
        (False, (True, True), (4, 5), ["cross_owner_transfer"]),
        (
            True,
            (False, True),
            (4, 5),
            [
                "cross_owner_transfer",
                "different_transfer_dates",
                "unreconciled_transfer_legs",
            ],
        ),
    ],
)
def test_graph_pair_state_is_withdrawal_oriented_once(
    snapshots, different_date, reconciled, owners, expected
):
    accounts = [{"id": 10, "user": owners[0]}, {"id": 20, "user": owners[1]}]
    rows = transfer_rows()
    rows[0]["reconciled"], rows[1]["reconciled"] = reconciled
    if different_date:
        rows[1]["datetime"] = "2026-09-13T00:00:00+00:00"

    findings = snapshots.audit_graph(accounts, list(reversed(rows)))

    assert finding_kinds(findings) == expected
    for finding in findings:
        assert finding["ids"] == [1, 2]
        if finding["kind"] != "cross_owner_transfer":
            assert finding["severity"] == "candidate"


@pytest.mark.parametrize(
    "row_index,field,value",
    [
        (1, "sender_transaction", 999),
        (1, "entity", "DepositTransaction"),
        (0, "recipient_account", 999),
        (1, "sender_account", 999),
    ],
    ids=["reverse-id", "opposite-entity", "target-account", "reverse-account"],
)
def test_graph_rejects_each_broken_reciprocity_dimension(
    snapshots, row_index, field, value
):
    accounts = [{"id": 10, "user": 4}, {"id": 20, "user": 5}]
    rows = transfer_rows()
    rows[1]["datetime"] = "2026-09-13T00:00:00+00:00"
    rows[1]["reconciled"] = False
    rows[row_index][field] = value

    findings = snapshots.audit_graph(accounts, rows)

    assert not (set(finding_kinds(findings)) & PAIR_FINDINGS)
    assert any(
        finding["kind"] in {"missing_transfer_leg", "nonreciprocal_transfer"}
        for finding in findings
    )


@pytest.mark.parametrize("shape", ["missing", "self", "cycle"])
def test_invalid_transfer_graphs_never_receive_pair_state(snapshots, shape):
    accounts = [{"id": 10, "user": 4}, {"id": 20, "user": 5}]
    rows = transfer_rows()
    rows[1]["datetime"] = "2026-09-13T00:00:00+00:00"
    rows[1]["reconciled"] = False
    if shape == "missing":
        rows = rows[:1]
    elif shape == "self":
        rows[0]["recipient_transaction"] = 1
    else:
        rows[1] = deepcopy(rows[0])
        rows[1].update(
            {
                "id": 2,
                "account": 20,
                "recipient_account": 10,
                "recipient_transaction": 1,
            }
        )

    findings = snapshots.audit_graph(accounts, rows)

    assert not (set(finding_kinds(findings)) & PAIR_FINDINGS)
    assert any(
        finding["kind"] in {"missing_transfer_leg", "nonreciprocal_transfer"}
        for finding in findings
    )


@pytest.mark.parametrize(
    "value,expected", [(None, None), (0, "0"), (2, "2"), (-2.5, "-2.5")]
)
def test_cached_balance_preserves_supported_values(reads, value, expected):
    assert reads.cached_balance_value(value) == expected


@pytest.mark.parametrize(
    "value,error",
    [
        (True, TypeError),
        ("private-balance", TypeError),
        (b"private-balance", TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
        (float("-inf"), ValueError),
    ],
)
def test_cached_balance_rejects_untrusted_or_nonfinite_values(reads, value, error):
    with pytest.raises(error):
        reads.cached_balance_value(value)


@pytest.mark.parametrize(
    "value,expected",
    [
        (Decimal(0), "0"),
        (Decimal("-2.5"), "-2.5"),
        (Decimal("123.4567890123456789"), "123.4567890123456789"),
    ],
)
def test_financial_decimal_output_preserves_finite_representation(
    reads, value, expected
):
    assert reads.json_value(value) == expected


@pytest.mark.parametrize(
    "value", [Decimal("Infinity"), Decimal("-Infinity"), Decimal("NaN")]
)
def test_financial_decimal_output_rejects_nonfinite_values(reads, value):
    with pytest.raises(ValueError, match="non-finite decimal"):
        reads.json_value(value)


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


def run_read_script(store, command, *args):
    script = Path(__file__).resolve().parents[2] / "scripts" / f"{command}.py"
    return subprocess.run(
        [sys.executable, str(script), "--db", str(store), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def assert_bounded_read_error(result, expected_error):
    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr) == {
        "status": "error",
        "error": expected_error,
        "message": "Read failed; check database, schema and command arguments",
    }
    assert "Traceback" not in result.stderr


def replace_transaction_with_transfer_pair(store, *, deposit_date=100):
    with sqlite3.connect(store) as connection:
        connection.executescript("""
            INSERT INTO Z_PRIMARYKEY VALUES
              (45, 'TransferDepositTransaction', 36),
              (46, 'TransferWithdrawTransaction', 36);
            INSERT INTO ZUSER VALUES (5, 'other-owner@example.test');
            INSERT INTO ZSYNCOBJECT
              (Z_PK,Z_ENT,ZOBJECTCREATIONDATE,ZGID,ZDISPLAYORDER,ZGROUPID,ZNAME,
               ZCURRENCYNAME,ZOPENINGBALANCE,ZUSER,ZARCHIVED,ZBALLANCE)
            VALUES (20,12,0,'recipient-account',1,0,'Recipient account','EUR',0,5,0,0);
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZRECIPIENTACCOUNT1 INTEGER;
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZRECIPIENTTRANSACTION INTEGER;
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZORIGINALRECIPIENTAMOUNT REAL;
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZORIGINALRECIPIENTCURRENCY TEXT;
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZORIGINALFEE REAL;
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZORIGINALFEECURRENCY TEXT;
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZSENDERACCOUNT INTEGER;
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZSENDERTRANSACTION INTEGER;
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZORIGINALSENDERAMOUNT REAL;
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZORIGINALSENDERCURRENCY TEXT;
            DELETE FROM ZSYNCOBJECT WHERE Z_PK = 11;
            INSERT INTO ZSYNCOBJECT
              (Z_PK,Z_ENT,ZOBJECTCREATIONDATE,ZGID,ZRECONCILED,ZAMOUNT1,ZDESC2,
               ZDATE1,ZACCOUNT2,ZRECIPIENTACCOUNT1,ZRECIPIENTTRANSACTION,
               ZORIGINALAMOUNT,ZORIGINALCURRENCY,ZORIGINALRECIPIENTAMOUNT,
               ZORIGINALRECIPIENTCURRENCY,ZORIGINALEXCHANGERATE,ZSTATUS1,ZFLAGS1)
            VALUES (11,46,0,'synthetic-withdrawal',1,-10,'Synthetic transfer',100,
                    10,20,12,-10,'EUR',10,'EUR',1,1,0);
        """)
        connection.execute(
            """
            INSERT INTO ZSYNCOBJECT
              (Z_PK,Z_ENT,ZOBJECTCREATIONDATE,ZGID,ZRECONCILED,ZAMOUNT1,ZDESC2,
               ZDATE1,ZACCOUNT2,ZSENDERACCOUNT,ZSENDERTRANSACTION,ZORIGINALAMOUNT,
               ZORIGINALCURRENCY,ZORIGINALSENDERAMOUNT,ZORIGINALSENDERCURRENCY,
               ZORIGINALEXCHANGERATE,ZSTATUS1,ZFLAGS1)
            VALUES (12,45,0,'synthetic-deposit',1,10,'Synthetic transfer',?,
                    20,10,11,10,'EUR',-10,'EUR',1,1,0)
            """,
            (deposit_date,),
        )


def test_snapshot_receiving_account_keeps_one_whole_graph_pair_observation(
    reads, synthetic_store
):
    replace_transaction_with_transfer_pair(synthetic_store)

    result = run_read_script(synthetic_store, "snapshot", "--account", "20")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [row["id"] for row in payload["transactions"]] == [12]
    assert payload["audit"] == [{"kind": "cross_owner_transfer", "ids": [11, 12]}]


def test_snapshot_cutoff_hidden_counterpart_is_not_missing_or_duplicated(
    reads, synthetic_store
):
    replace_transaction_with_transfer_pair(synthetic_store, deposit_date=200)

    result = run_read_script(
        synthetic_store,
        "snapshot",
        "--account",
        "10",
        "--until",
        "2001-01-01T00:02:00+00:00",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [row["id"] for row in payload["transactions"]] == [11]
    assert finding_kinds(payload["audit"]) == [
        "cross_owner_transfer",
        "different_transfer_dates",
    ]
    assert all(finding["ids"] == [11, 12] for finding in payload["audit"])
    assert "missing_transfer_leg" not in finding_kinds(payload["audit"])


@pytest.mark.parametrize(
    "value,expected_error,private_text",
    [
        ("private-balance", "TypeError", "private-balance"),
        (sqlite3.Binary(b"private-balance"), "TypeError", "private-balance"),
        (float("inf"), "ValueError", None),
        (float("-inf"), "ValueError", None),
    ],
)
def test_snapshot_rejects_unsupported_selected_cached_balance(
    reads, synthetic_store, value, expected_error, private_text
):
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(
            "UPDATE ZSYNCOBJECT SET ZBALLANCE = ? WHERE Z_PK = 10", (value,)
        )

    result = run_read_script(synthetic_store, "snapshot", "--account", "10")

    assert_bounded_read_error(result, expected_error)
    if private_text is not None:
        assert private_text not in result.stderr


def test_snapshot_does_not_validate_unselected_cached_balance(reads, synthetic_store):
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(
            """
            INSERT INTO ZSYNCOBJECT
              (Z_PK,Z_ENT,ZOBJECTCREATIONDATE,ZGID,ZDISPLAYORDER,ZGROUPID,ZNAME,
               ZCURRENCYNAME,ZOPENINGBALANCE,ZUSER,ZARCHIVED,ZBALLANCE)
            VALUES (12,12,0,'unselected-balance',1,0,'Other account','EUR',0,4,0,
                    'private-unselected-balance')
            """
        )

    result = run_read_script(
        synthetic_store, "snapshot", "--account", "10", "--until", "2001-01-02"
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [row["id"] for row in payload["accounts"]] == [10]
    assert "private-unselected-balance" not in result.stdout


def add_category_assignment(store, amount):
    with sqlite3.connect(store) as connection:
        connection.executescript("""
            INSERT INTO Z_PRIMARYKEY VALUES (60, 'CategoryAssigment', 0);
            CREATE TABLE ZCATEGORYASSIGMENT (
              Z_PK INTEGER PRIMARY KEY,
              ZCATEGORY INTEGER,
              ZTRANSACTION INTEGER,
              ZAMOUNT REAL);
        """)
        connection.execute(
            "INSERT INTO ZCATEGORYASSIGMENT VALUES (1, 70, 11, ?)", (amount,)
        )


@pytest.mark.parametrize(
    "command,args",
    [
        ("snapshot", ("--until", "2001-01-02")),
        (
            "transactions",
            ("--with-categories", "--format", "json", "--diagnostics"),
        ),
        ("transactions", ("--with-categories",)),
    ],
)
def test_category_amount_output_rejects_nonfinite_decimal(
    reads, synthetic_store, command, args
):
    add_category_assignment(synthetic_store, float("inf"))

    result = run_read_script(synthetic_store, command, *args)

    assert_bounded_read_error(result, "ValueError")


@pytest.mark.parametrize(
    "args",
    [
        ("--format", "json"),
        ("--format", "json", "--diagnostics"),
        (),
        ("--fields", "id,amount"),
        ("--all-fields", "--format", "json"),
        ("--list-fields",),
    ],
)
def test_transaction_amount_output_rejects_nonfinite_decimal(
    reads, synthetic_store, args
):
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(
            """
            UPDATE ZSYNCOBJECT
            SET ZAMOUNT1 = ?, ZORIGINALAMOUNT = ?
            WHERE Z_PK = 11
            """,
            (float("inf"), float("inf")),
        )

    result = run_read_script(synthetic_store, "transactions", *args)

    assert_bounded_read_error(result, "ValueError")


def add_holding(store, quantity):
    with sqlite3.connect(store) as connection:
        connection.executescript("""
            INSERT INTO Z_PRIMARYKEY VALUES (24, 'InvestmentHolding', 0);
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZINVESTMENTACCOUNT INTEGER;
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZOPENNINGNUMBEROFSHARES REAL;
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZSYMBOL TEXT;
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZHOLDINGTYPE TEXT;
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZDESC TEXT;
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZISPRICEPERSHAREAVAILABLEONLINE INTEGER;
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZINVESTMENTOBJECTTYPE INTEGER;
            ALTER TABLE ZSYNCOBJECT ADD COLUMN ZCOSTBASISOFMISSINGOBSHARES REAL;
        """)
        connection.execute(
            """
            INSERT INTO ZSYNCOBJECT
              (Z_PK,Z_ENT,ZOBJECTCREATIONDATE,ZGID,ZINVESTMENTACCOUNT,
               ZOPENNINGNUMBEROFSHARES,ZNUMBEROFSHARES,ZPRICEPERSHARE,ZSYMBOL,
               ZHOLDINGTYPE,ZDESC,ZISPRICEPERSHAREAVAILABLEONLINE,
               ZINVESTMENTOBJECTTYPE,ZCOSTBASISOFMISSINGOBSHARES)
            VALUES (12,24,0,'synthetic-holding',10,0,?,?, 'SYN',NULL,
                    'Synthetic holding',0,0,0)
            """,
            (quantity, 1),
        )


@pytest.mark.parametrize("output_format", ["json", "table"])
def test_holding_quantity_output_rejects_nonfinite_decimal(
    reads, synthetic_store, output_format
):
    add_holding(synthetic_store, float("inf"))

    result = run_read_script(
        synthetic_store, "holdings", "--account", "10", "--format", output_format
    )

    assert_bounded_read_error(result, "ValueError")


@pytest.mark.parametrize(
    "kind,value,expected",
    [
        ("category", -2.5, "-2.5"),
        ("category", 0, "0.0"),
        ("holding", -2.5, "-2.5"),
        ("holding", 0, "0.0"),
    ],
)
def test_list_outputs_preserve_supported_finite_numbers(
    reads, synthetic_store, kind, value, expected
):
    if kind == "category":
        add_category_assignment(synthetic_store, value)
        result = run_read_script(
            synthetic_store,
            "transactions",
            "--with-categories",
            "--format",
            "json",
        )
        assert result.returncode == 0, result.stderr
        actual = json.loads(result.stdout)[0]["categories"][0]["amount"]
    else:
        add_holding(synthetic_store, value)
        result = run_read_script(
            synthetic_store, "holdings", "--account", "10", "--format", "json"
        )
        assert result.returncode == 0, result.stderr
        actual = json.loads(result.stdout)[0]["number_of_shares"]
    assert actual == expected
