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
    con.execute(
        "INSERT INTO ZSYNCOBJECT (Z_PK, Z_ENT, ZUSER) VALUES (100, 10, 1)"
    )
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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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


def test_reassign_plan_reuses_one_new_payee_for_matching_descriptions(tmp_path: Path) -> None:
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
