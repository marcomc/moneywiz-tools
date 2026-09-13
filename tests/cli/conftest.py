import shutil
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def moneywiz_command() -> list[str]:
    repo_root = Path(__file__).resolve().parents[2]
    return [
        "bash",
        str(repo_root / "moneywiz.sh"),
        "--db",
        str(repo_root / "tests/test_db.sqlite"),
    ]


@pytest.fixture
def synthetic_store(tmp_path: Path) -> Path:
    """Build the minimal synthetic store shared by read-contract tests."""
    store = tmp_path / "read-fixture.sqlite"
    with sqlite3.connect(store) as connection:
        connection.executescript("""
            CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER, Z_NAME TEXT, Z_SUPER INTEGER);
            INSERT INTO Z_PRIMARYKEY VALUES
              (9, 'Account', 0), (12, 'CashAccount', 9),
              (35, 'Tag', 0),
              (36, 'Transaction', 0), (37, 'DepositTransaction', 36);
            CREATE TABLE ZUSER (Z_PK INTEGER PRIMARY KEY, ZSYNCLOGIN TEXT);
            INSERT INTO ZUSER VALUES (4, 'synthetic@example.test');
            CREATE TABLE ZSYNCOBJECT (
              Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, ZOBJECTCREATIONDATE REAL, ZGID TEXT,
              ZDISPLAYORDER INTEGER, ZGROUPID INTEGER, ZNAME TEXT, ZCURRENCYNAME TEXT,
              ZOPENINGBALANCE REAL, ZINFO TEXT, ZUSER INTEGER, ZARCHIVED INTEGER, ZBALLANCE REAL,
              ZRECONCILED INTEGER, ZAMOUNT1 REAL, ZDESC2 TEXT, ZDATE1 REAL, ZNOTES1 TEXT,
              ZACCOUNT2 INTEGER, ZPAYEE2 INTEGER, ZORIGINALCURRENCY TEXT, ZORIGINALAMOUNT REAL,
              ZORIGINALEXCHANGERATE REAL, ZNUMBEROFSHARES REAL, ZPRICEPERSHARE REAL,
              ZSTATUS1 INTEGER, ZFLAGS1 INTEGER);
            INSERT INTO ZSYNCOBJECT
              (Z_PK,Z_ENT,ZOBJECTCREATIONDATE,ZGID,ZDISPLAYORDER,ZGROUPID,ZNAME,ZCURRENCYNAME,
               ZOPENINGBALANCE,ZUSER,ZARCHIVED,ZBALLANCE)
              VALUES (10,12,0,'synthetic-account',0,0,'Synthetic cash','EUR',0,4,0,2);
            INSERT INTO ZSYNCOBJECT
              (Z_PK,Z_ENT,ZOBJECTCREATIONDATE,ZGID,ZRECONCILED,ZAMOUNT1,ZDESC2,ZDATE1,
               ZACCOUNT2,ZORIGINALCURRENCY,ZORIGINALAMOUNT,ZSTATUS1,ZFLAGS1)
              VALUES (11,37,0,'synthetic-income',0,2,'Synthetic income',100,10,'EUR',2,1,0);
            CREATE TABLE Z_36TAGS (
              Z_36TRANSACTIONS INTEGER,
              Z_35TAGS INTEGER);
        """)
    return store


@pytest.fixture
def partial_metadata_store(synthetic_store: Path, tmp_path: Path) -> Path:
    """Remove tag metadata so relationship storage is intentionally unknown."""
    store = tmp_path / "partial-metadata-read-fixture.sqlite"
    shutil.copy2(synthetic_store, store)
    with sqlite3.connect(store) as connection:
        connection.executescript("""
            DROP TABLE Z_36TAGS;
            DELETE FROM Z_PRIMARYKEY WHERE Z_ENT = 35;
        """)
    return store
