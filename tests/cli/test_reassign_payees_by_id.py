import sqlite3
import subprocess
import sys
from pathlib import Path

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
