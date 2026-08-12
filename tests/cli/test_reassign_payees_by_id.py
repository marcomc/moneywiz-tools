import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import reassign_payees_by_id

TRANSACTION_TYPES = (
    "DepositTransaction",
    "InvestmentExchangeTransaction",
    "InvestmentBuyTransaction",
    "InvestmentSellTransaction",
    "ReconcileTransaction",
    "RefundTransaction",
    "TransferBudgetTransaction",
    "TransferDepositTransaction",
    "TransferWithdrawTransaction",
    "WithdrawTransaction",
)


def make_database(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER, Z_NAME TEXT);
        CREATE TABLE ZSYNCOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER,
            ZGID TEXT,
            ZNAME5 TEXT,
            ZUSER7 INTEGER,
            ZACCOUNT2 INTEGER,
            ZDESC2 TEXT,
            ZPAYEE2 INTEGER,
            ZUSER INTEGER
        );
        """
    )
    con.executemany(
        "INSERT INTO Z_PRIMARYKEY (Z_ENT, Z_NAME) VALUES (?, ?)",
        [(index + 40, name) for index, name in enumerate(TRANSACTION_TYPES)]
        + [(29, "Payee")],
    )
    withdraw_entity = 40 + TRANSACTION_TYPES.index("WithdrawTransaction")
    con.execute("INSERT INTO ZSYNCOBJECT (Z_PK, Z_ENT, ZUSER) VALUES (100, 10, 1)")
    con.execute(
        """
        INSERT INTO ZSYNCOBJECT (Z_PK, Z_ENT, ZGID, ZNAME5, ZUSER7)
        VALUES (200, 29, 'payee-existing', 'Vodafone\u00a0Pag\u00a0Ricar\u00a0Au', 1)
        """
    )
    con.executemany(
        """
        INSERT INTO ZSYNCOBJECT
        (Z_PK, Z_ENT, ZGID, ZACCOUNT2, ZDESC2, ZPAYEE2)
        VALUES (?, ?, ?, 100, ?, 999)
        """,
        [
            (300, withdraw_entity, "transaction-existing", " Vodafone Pag Ricar Au "),
            (301, withdraw_entity, "transaction-new-one", "New Merchant"),
            (302, withdraw_entity, "transaction-new-two", "New Merchant"),
        ],
    )
    con.commit()
    con.close()


def run_reassign(db_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts/reassign_payees_by_id.py"
    return subprocess.run(
        [sys.executable, str(script), "--db", str(db_path), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def test_moneywiz_process_check_accepts_only_stopped_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reassign_payees_by_id.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1),
    )

    reassign_payees_by_id._require_moneywiz_stopped()


@pytest.mark.parametrize("returncode", [0, 2, -9])
def test_moneywiz_process_check_rejects_running_or_abnormal_status(
    monkeypatch: pytest.MonkeyPatch, returncode: int
) -> None:
    monkeypatch.setattr(
        reassign_payees_by_id.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], returncode),
    )

    with pytest.raises(reassign_payees_by_id.ReassignmentError):
        reassign_payees_by_id._require_moneywiz_stopped()


def test_moneywiz_process_check_rejects_inspection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_inspection(*_args: object, **_kwargs: object) -> None:
        raise OSError("pgrep unavailable")

    monkeypatch.setattr(reassign_payees_by_id.subprocess, "run", fail_inspection)

    with pytest.raises(
        reassign_payees_by_id.ReassignmentError,
        match="Cannot verify whether MoneyWiz 2026 is running",
    ):
        reassign_payees_by_id._require_moneywiz_stopped()


@pytest.mark.parametrize("outcome", [0, 2, OSError("pgrep unavailable")])
def test_process_check_failure_stops_before_writer_preflight(
    monkeypatch: pytest.MonkeyPatch, outcome: int | OSError
) -> None:
    commands: list[list[str]] = []

    def inspect(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if isinstance(outcome, OSError):
            raise outcome
        return subprocess.CompletedProcess(command, outcome)

    monkeypatch.setattr(reassign_payees_by_id.subprocess, "run", inspect)
    monkeypatch.setattr(
        reassign_payees_by_id,
        "require_write_capability",
        lambda *_args, **_kwargs: pytest.fail(
            "writer compatibility preflight ran after process-check failure"
        ),
    )

    with pytest.raises(reassign_payees_by_id.ReassignmentError):
        reassign_payees_by_id.apply_coredata_payload(
            Path("unused.sqlite"),
            {"schema_version": 1, "operations": []},
            capability="write.reassign-payees-by-id",
        )

    assert commands == [["pgrep", "-x", "MoneyWiz"]]


def test_reassign_plan_normalizes_existing_unicode_payee(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)

    result = run_reassign(db_path, "--from-payee-id", "999", "--show-plan")

    assert result.returncode == 0, result.stderr
    assert "existing payee 200 ('Vodafone" in result.stdout
    assert "Summary: processed=3, created=1, updated=3" in result.stdout


def test_reassign_plan_reuses_one_new_payee_for_matching_descriptions(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)

    result = run_reassign(db_path, "--from-payee-id", "999", "--show-plan")

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("new payee 'New Merchant'") == 2
    assert "created=1, updated=3" in result.stdout


def test_reassign_invalid_parameters_are_clean_errors(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)

    result = run_reassign(
        db_path,
        "--from-empty-payee",
        "--empty-desc-target-payee-id",
        "404",
    )

    assert result.returncode == 2
    assert "not a valid Payee id" in result.stderr
    assert "Traceback" not in result.stderr


def prepare_empty_description_fallback(
    db_path: Path, *, payee_id: int, payee_user_id: int
) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            INSERT INTO ZSYNCOBJECT (Z_PK, Z_ENT, ZGID, ZNAME5, ZUSER7)
            VALUES (?, 29, ?, 'Fallback', ?)
            """,
            (payee_id, f"payee-{payee_id}", payee_user_id),
        )
        con.execute(
            "UPDATE ZSYNCOBJECT SET ZDESC2 = '', ZPAYEE2 = NULL WHERE Z_PK = 300"
        )


def test_reassign_accepts_same_user_fallback_payee(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)
    prepare_empty_description_fallback(db_path, payee_id=201, payee_user_id=1)

    result = run_reassign(
        db_path,
        "--from-empty-payee",
        "--empty-desc-target-payee-id",
        "201",
        "--show-plan",
    )

    assert result.returncode == 0, result.stderr
    assert (
        "tx 300 (WithdrawTransaction) -> existing payee 201 ('Fallback')"
        in result.stdout
    )


def test_reassign_rejects_cross_user_fallback_payee(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)
    prepare_empty_description_fallback(db_path, payee_id=201, payee_user_id=2)

    result = run_reassign(
        db_path,
        "--from-empty-payee",
        "--empty-desc-target-payee-id",
        "201",
    )

    assert result.returncode == 2
    assert (
        "Fallback payee id 201 belongs to user 2, but transaction 300 belongs to user 1"
        in result.stderr
    )
    assert "Traceback" not in result.stderr


def test_reassign_rejects_mixed_user_fallback_plan_atomically(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)
    prepare_empty_description_fallback(db_path, payee_id=201, payee_user_id=1)
    withdraw_entity = 40 + TRANSACTION_TYPES.index("WithdrawTransaction")
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT INTO ZSYNCOBJECT (Z_PK, Z_ENT, ZUSER) VALUES (101, 10, 2)")
        con.execute(
            """
            INSERT INTO ZSYNCOBJECT
            (Z_PK, Z_ENT, ZGID, ZACCOUNT2, ZDESC2, ZPAYEE2)
            VALUES (303, ?, 'transaction-user-two', 101, '', NULL)
            """,
            (withdraw_entity,),
        )

    result = run_reassign(
        db_path,
        "--from-empty-payee",
        "--empty-desc-target-payee-id",
        "201",
        "--apply",
    )

    assert result.returncode == 2
    assert "transaction 303 belongs to user 2" in result.stderr
    assert "-- APPLY --" not in result.stdout
