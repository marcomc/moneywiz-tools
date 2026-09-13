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


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-03-29", datetime(2026, 3, 28, 23, tzinfo=UTC)),
        ("2026-10-25", datetime(2026, 10, 24, 22, tzinfo=UTC)),
    ],
)
def test_date_only_cutoff_is_inclusive_local_midnight(reads, value, expected):
    boundary, exclusive = reads.cutoff(value, "Europe/Rome")
    assert boundary == expected
    assert exclusive is False


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
    ] == [1, 2]


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


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_json_value_rejects_nonfinite_float_leaves(reads, value):
    with pytest.raises(ValueError, match="non-finite float"):
        reads.json_value({"raw": [value]})


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
            "original_amount": "-10",
            "original_currency": "EUR",
            "recipient_amount": "12",
            "recipient_currency": "USD",
            "original_fee": None,
            "original_exchange_rate": "1.2",
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
            "original_amount": "12",
            "original_currency": "USD",
            "sender_amount": "-10",
            "sender_currency": "EUR",
            "original_fee": None,
            "original_fee_currency": None,
            "original_exchange_rate": "1.2",
        },
    ]


PAIR_FINDINGS = {
    "cross_owner_transfer",
    "different_transfer_dates",
    "mismatched_transfer_fx",
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


@pytest.mark.parametrize(
    "row_index,field,value",
    [
        (1, "sender_amount", "-11"),
        (1, "sender_currency", "GBP"),
        (1, "original_amount", "13"),
        (1, "original_currency", "GBP"),
        (1, "original_exchange_rate", "0.833333"),
    ],
    ids=[
        "sender-amount",
        "sender-currency",
        "recipient-amount",
        "recipient-currency",
        "exchange-rate-direction",
    ],
)
def test_graph_reports_one_bounded_mismatched_transfer_fx(
    snapshots, row_index, field, value
):
    accounts = [{"id": 10, "user": 4}, {"id": 20, "user": 4}]
    rows = transfer_rows()
    rows[row_index][field] = value

    assert snapshots.audit_graph(accounts, rows) == [
        {"kind": "mismatched_transfer_fx", "ids": [1, 2]}
    ]


def test_graph_accepts_consistent_same_currency_transfer_fx(snapshots):
    accounts = [{"id": 10, "user": 4}, {"id": 20, "user": 4}]
    rows = transfer_rows()
    rows[0].update(
        recipient_amount="10", recipient_currency="EUR", original_exchange_rate="1"
    )
    rows[1].update(
        original_amount="10", original_currency="EUR", original_exchange_rate="1"
    )

    assert snapshots.audit_graph(accounts, rows) == []


@pytest.mark.parametrize(
    "fee,fee_currency,deposit_original_amount",
    [
        (None, None, "12"),
        ("0", "USD", "12"),
        ("1", "USD", "11"),
        ("-1", "USD", "13"),
    ],
    ids=["absent", "zero", "positive", "negative"],
)
def test_graph_accepts_deposit_fee_adjusted_recipient_amount(
    snapshots, fee, fee_currency, deposit_original_amount
):
    accounts = [{"id": 10, "user": 4}, {"id": 20, "user": 4}]
    rows = transfer_rows()
    rows[1]["original_amount"] = deposit_original_amount
    rows[1]["original_fee"] = fee
    rows[1]["original_fee_currency"] = fee_currency

    assert snapshots.audit_graph(accounts, rows) == []


@pytest.mark.parametrize("fee_currency", [None, "GBP"], ids=["missing", "different"])
def test_graph_rejects_deposit_fee_outside_recipient_currency(snapshots, fee_currency):
    accounts = [{"id": 10, "user": 4}, {"id": 20, "user": 4}]
    rows = transfer_rows()
    rows[1].update(
        original_amount="11",
        original_fee="1",
        original_fee_currency=fee_currency,
    )

    assert snapshots.audit_graph(accounts, rows) == [
        {"kind": "mismatched_transfer_fx", "ids": [1, 2]}
    ]


def test_graph_does_not_apply_withdrawal_fee_to_recipient_amount(snapshots):
    accounts = [{"id": 10, "user": 4}, {"id": 20, "user": 4}]
    rows = transfer_rows()
    rows[0]["original_fee"] = "1"

    assert snapshots.audit_graph(accounts, rows) == []


def test_graph_reports_recipient_amount_mismatch_after_deposit_fee(snapshots):
    accounts = [{"id": 10, "user": 4}, {"id": 20, "user": 4}]
    rows = transfer_rows()
    rows[1]["original_amount"] = "10"
    rows[1]["original_fee"] = "1"

    assert snapshots.audit_graph(accounts, rows) == [
        {"kind": "mismatched_transfer_fx", "ids": [1, 2]}
    ]


@pytest.mark.parametrize(
    "field,value",
    [("sender_amount", "-10.0009"), ("original_exchange_rate", "1.2009")],
    ids=["duplicated-amount", "duplicated-rate"],
)
def test_graph_does_not_apply_model_tolerance_across_transfer_legs(
    snapshots, field, value
):
    accounts = [{"id": 10, "user": 4}, {"id": 20, "user": 4}]
    rows = transfer_rows()
    rows[1][field] = value

    assert snapshots.audit_graph(accounts, rows) == [
        {"kind": "mismatched_transfer_fx", "ids": [1, 2]}
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


def test_snapshot_selected_unreadable_account_is_partial_not_missing(
    reads, synthetic_store
):
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute("UPDATE ZSYNCOBJECT SET ZNAME = NULL WHERE Z_PK = 10")

    result = run_read_script(synthetic_store, "snapshot", "--account", "10")

    assert result.returncode == 3, result.stderr
    payload = json.loads(result.stdout)
    assert payload["accounts"] == []
    assert [row["id"] for row in payload["transactions"]] == [11]
    account_report = payload["completeness"]["managers"]["accounts"]
    assert account_report["source_ids"] == [10]
    assert account_report["parsed_ids"] == []
    assert account_report["skipped"][0]["record_id"] == 10
    assert "Traceback" not in result.stderr


def test_snapshot_selected_genuinely_absent_account_is_bounded_error(
    reads, synthetic_store
):
    result = run_read_script(synthetic_store, "snapshot", "--account", "999")

    assert_bounded_read_error(result, "ValueError")


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


@pytest.mark.parametrize(
    "command,args",
    [
        ("snapshot", ()),
        ("transactions", ()),
        ("transactions", ("--format", "json")),
    ],
)
def test_binary_transaction_description_is_a_bounded_read_error(
    reads, synthetic_store, command, args
):
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(
            "UPDATE ZSYNCOBJECT SET ZDESC2 = ? WHERE Z_PK = 11",
            (sqlite3.Binary(b"\x01\x02"),),
        )
    result = run_read_script(synthetic_store, command, *args)

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
    assert "b'" not in result.stderr


@pytest.mark.parametrize("command", ["snapshot", "transactions"])
def test_out_of_range_offset_is_a_bounded_read_error(reads, synthetic_store, command):
    script = Path(__file__).resolve().parents[2] / "scripts" / f"{command}.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--db",
            str(synthetic_store),
            "--until",
            "9999-12-31T23:59:59-01:00",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["error"] == "OverflowError"
    assert error["message"] == (
        "Read failed; check database, schema and command arguments"
    )
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("command", ["snapshot", "transactions"])
def test_maximum_date_is_a_bounded_read_error(reads, synthetic_store, command):
    result = run_read_script(synthetic_store, command, "--until", "9999-12-31")

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


@pytest.mark.parametrize("command", ["snapshot", "transactions"])
@pytest.mark.parametrize("offset,expected_ids", [(0, [11]), (1, [])])
def test_date_only_cli_cutoff_is_inclusive_midnight_not_end_of_day(
    reads, synthetic_store, command, offset, expected_ids
):
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(
            "UPDATE ZSYNCOBJECT SET ZDATE1 = ? WHERE Z_PK = 11", (86400 + offset,)
        )
    extra = ("--format", "json") if command == "transactions" else ()

    result = run_read_script(synthetic_store, command, "--until", "2001-01-02", *extra)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    rows = payload["transactions"] if command == "snapshot" else payload
    assert [row["id"] for row in rows] == expected_ids


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


def test_snapshot_reports_mismatched_transfer_fx_from_native_pair_fields(
    reads, synthetic_store
):
    replace_transaction_with_transfer_pair(synthetic_store)
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(
            """
            UPDATE ZSYNCOBJECT
            SET ZAMOUNT1 = 12,
                ZORIGINALAMOUNT = 12,
                ZORIGINALCURRENCY = 'USD',
                ZORIGINALEXCHANGERATE = 1.2
            WHERE Z_PK = 12
            """
        )

    result = run_read_script(synthetic_store, "snapshot")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["completeness"]["complete"] is True
    assert finding_kinds(payload["audit"]) == [
        "cross_owner_transfer",
        "mismatched_transfer_fx",
    ]
    assert payload["audit"][1] == {
        "kind": "mismatched_transfer_fx",
        "ids": [11, 12],
    }


def test_snapshot_accepts_valid_deposit_fee_adjusted_transfer_pair(
    reads, synthetic_store
):
    replace_transaction_with_transfer_pair(synthetic_store)
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(
            """
            UPDATE ZSYNCOBJECT
            SET ZAMOUNT1 = 9,
                ZORIGINALAMOUNT = 9,
                ZORIGINALFEE = 1,
                ZORIGINALFEECURRENCY = 'EUR'
            WHERE Z_PK = 12
            """
        )

    result = run_read_script(synthetic_store, "snapshot")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["completeness"]["complete"] is True
    assert payload["audit"] == [{"kind": "cross_owner_transfer", "ids": [11, 12]}]


def test_snapshot_rejects_deposit_fee_in_different_recipient_currency(
    reads, synthetic_store
):
    replace_transaction_with_transfer_pair(synthetic_store)
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(
            """
            UPDATE ZSYNCOBJECT
            SET ZAMOUNT1 = 9,
                ZORIGINALAMOUNT = 9,
                ZORIGINALFEE = 1,
                ZORIGINALFEECURRENCY = 'GBP'
            WHERE Z_PK = 12
            """
        )

    result = run_read_script(synthetic_store, "snapshot")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["completeness"]["complete"] is True
    assert finding_kinds(payload["audit"]) == [
        "cross_owner_transfer",
        "mismatched_transfer_fx",
    ]
    assert payload["audit"][1] == {
        "kind": "mismatched_transfer_fx",
        "ids": [11, 12],
    }


@pytest.mark.parametrize("mismatch", ["btc-amount", "exchange-rate"])
def test_snapshot_detects_exact_cross_leg_mismatch_with_valid_models(
    reads, synthetic_store, mismatch
):
    replace_transaction_with_transfer_pair(synthetic_store)
    deposit_amount = 1.0009 if mismatch == "btc-amount" else 1
    deposit_sender_amount = -1.0009 if mismatch == "btc-amount" else -1
    deposit_rate = 1 if mismatch == "btc-amount" else 1.0009
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute("UPDATE ZSYNCOBJECT SET ZUSER = 4 WHERE Z_PK = 20")
        connection.execute(
            """
            UPDATE ZSYNCOBJECT
            SET ZAMOUNT1 = -1,
                ZORIGINALAMOUNT = -1,
                ZORIGINALCURRENCY = 'BTC',
                ZORIGINALRECIPIENTAMOUNT = 1,
                ZORIGINALRECIPIENTCURRENCY = 'BTC',
                ZORIGINALEXCHANGERATE = 1
            WHERE Z_PK = 11
            """
        )
        connection.execute(
            """
            UPDATE ZSYNCOBJECT
            SET ZAMOUNT1 = ?,
                ZORIGINALAMOUNT = ?,
                ZORIGINALCURRENCY = 'BTC',
                ZORIGINALSENDERAMOUNT = ?,
                ZORIGINALSENDERCURRENCY = 'BTC',
                ZORIGINALFEE = NULL,
                ZORIGINALFEECURRENCY = NULL,
                ZORIGINALEXCHANGERATE = ?
            WHERE Z_PK = 12
            """,
            (
                deposit_amount,
                deposit_amount,
                deposit_sender_amount,
                deposit_rate,
            ),
        )

    result = run_read_script(synthetic_store, "snapshot")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["completeness"]["complete"] is True
    assert payload["audit"] == [{"kind": "mismatched_transfer_fx", "ids": [11, 12]}]


@pytest.mark.parametrize("column", ["ZSTATUS1", "ZFLAGS1"])
@pytest.mark.parametrize(
    "value",
    [None, "private-native-state", 1.5, sqlite3.Binary(b"private-native-state")],
    ids=["null", "text", "real", "blob"],
)
def test_snapshot_rejects_malformed_native_status_and_flags(
    reads, synthetic_store, column, value
):
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(
            f"UPDATE ZSYNCOBJECT SET {column} = ? WHERE Z_PK = 11", (value,)
        )

    result = run_read_script(synthetic_store, "snapshot")

    assert_bounded_read_error(result, "TypeError")
    assert "private-native-state" not in result.stderr


@pytest.mark.parametrize("column", ["ZSTATUS1", "ZFLAGS1"])
def test_snapshot_rejects_missing_native_status_and_flag_columns(
    reads, synthetic_store, column
):
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(f"ALTER TABLE ZSYNCOBJECT DROP COLUMN {column}")

    result = run_read_script(synthetic_store, "snapshot")

    assert_bounded_read_error(result, "TypeError")


def test_snapshot_preserves_uninterpreted_native_integer_status_and_flags(
    reads, synthetic_store
):
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(
            "UPDATE ZSYNCOBJECT SET ZSTATUS1 = 7, ZFLAGS1 = -3 WHERE Z_PK = 11"
        )

    result = run_read_script(synthetic_store, "snapshot")

    assert result.returncode == 0, result.stderr
    transaction = json.loads(result.stdout)["transactions"][0]
    assert transaction["native_status"] == 7
    assert transaction["native_flags"] == -3


def test_native_transaction_integer_rejects_boolean(reads):
    record = SimpleNamespace(_raw={"ZSTATUS1": True})

    with pytest.raises(TypeError, match="not an integer"):
        reads.native_transaction_integer(record, "ZSTATUS1")


@pytest.mark.parametrize(
    "counterpart_state,expected_kind,expected_status",
    [
        ("skipped", "unreadable_transfer_leg", 3),
        ("absent", "missing_transfer_leg", 0),
    ],
)
def test_snapshot_distinguishes_unreadable_and_absent_transfer_legs(
    reads, synthetic_store, counterpart_state, expected_kind, expected_status
):
    replace_transaction_with_transfer_pair(synthetic_store)
    with sqlite3.connect(synthetic_store) as connection:
        if counterpart_state == "skipped":
            connection.execute("UPDATE ZSYNCOBJECT SET ZAMOUNT1 = NULL WHERE Z_PK = 12")
        else:
            connection.execute("DELETE FROM ZSYNCOBJECT WHERE Z_PK = 12")

    result = run_read_script(synthetic_store, "snapshot", "--account", "10")

    assert result.returncode == expected_status, result.stderr
    payload = json.loads(result.stdout)
    assert payload["audit"] == [{"kind": expected_kind, "ids": [11], "related_id": 12}]
    transaction_report = payload["completeness"]["managers"]["transactions"]
    if counterpart_state == "skipped":
        assert 12 in transaction_report["source_ids"]
        assert 12 not in transaction_report["parsed_ids"]
        assert transaction_report["skipped"][0]["record_id"] == 12
    else:
        assert 12 not in transaction_report["source_ids"]


@pytest.mark.parametrize(
    "value,expected_status",
    [(float("nan"), 0), (float("inf"), 3), (float("-inf"), 3)],
)
def test_transactions_all_fields_never_emits_nonstandard_json_float(
    reads, synthetic_store, value, expected_status
):
    with sqlite3.connect(synthetic_store) as connection:
        connection.execute(
            "UPDATE ZSYNCOBJECT SET ZPRICEPERSHARE = ? WHERE Z_PK = 11", (value,)
        )

    result = run_read_script(
        synthetic_store, "transactions", "--all-fields", "--format", "json"
    )

    # SQLite normalizes NaN to NULL; infinities reach the optional raw payload
    # and must become an explicit partial enrichment rather than invalid JSON.
    assert result.returncode == expected_status, result.stderr
    payload = json.loads(result.stdout, parse_constant=lambda token: pytest.fail(token))
    assert isinstance(payload, list)
    assert "NaN" not in result.stdout
    assert "Infinity" not in result.stdout
    if expected_status == 3:
        assert "enrichment_errors" in result.stderr


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
