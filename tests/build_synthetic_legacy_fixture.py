"""Create invented rows for legacy CLI checks; never read a financial store."""

import plistlib
import re
import sqlite3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
store = root / "tests/test_db.sqlite"
if store.exists():
    raise SystemExit("Refusing to overwrite existing fixture")
with sqlite3.connect(store) as c:
    for sql in re.findall(
        r"```sql\n(CREATE TABLE .*?)\n```",
        (root / "doc/DB-SCHEMA.md").read_text(),
        re.DOTALL,
    ):
        c.execute(sql)
    entities = [
        (9, "Account", 0),
        (12, "CashAccount", 9),
        (19, "Category", 0),
        (24, "InvestmentHolding", 0),
        (28, "Payee", 0),
        (35, "Tag", 0),
        (36, "Transaction", 0),
        (37, "DepositTransaction", 36),
        (45, "TransferDepositTransaction", 36),
        (46, "TransferWithdrawTransaction", 36),
        (47, "WithdrawTransaction", 36),
    ]
    c.executemany(
        "INSERT INTO Z_PRIMARYKEY (Z_ENT,Z_NAME,Z_SUPER,Z_MAX) VALUES (?,?,?,0)",
        entities,
    )
    c.executemany(
        "INSERT INTO ZUSER (Z_PK,ZSYNCLOGIN) VALUES (?,?)",
        [(1, "first@example.test"), (2, "second@example.test")],
    )
    metadata = {
        "NSStoreModelVersionChecksumKey": "KxT0qIvWI+7n1S58SHjQOJ8x50TIqI0l+sXzUGx8y18="
    }
    c.execute(
        "INSERT INTO Z_METADATA (Z_VERSION,Z_UUID,Z_PLIST) VALUES (1,?,?)",
        ("invented-legacy-fixture", plistlib.dumps(metadata)),
    )

    def row(**values):
        values = {"ZOBJECTCREATIONDATE": 0, "Z_OPT": 1, **values}
        c.execute(
            "INSERT INTO ZSYNCOBJECT ("
            + ",".join(values)
            + ") VALUES ("
            + ",".join("?" for _ in values)
            + ")",
            tuple(values.values()),
        )

    row(
        Z_PK=5309,
        Z_ENT=12,
        ZGID="invented-account",
        ZNAME="Invented cash",
        ZCURRENCYNAME="EUR",
        ZOPENINGBALANCE=0,
        ZUSER=2,
        ZDISPLAYORDER=0,
        ZGROUPID=0,
        ZARCHIVED=0,
        ZBALLANCE=2,
    )
    row(
        Z_PK=6000, Z_ENT=28, ZGID="invented-payee", ZNAME5="Invented merchant", ZUSER7=2
    )
    row(
        Z_PK=6100,
        Z_ENT=19,
        ZGID="invented-category",
        ZNAME2="Invented category",
        ZTYPE2=1,
        ZUSER3=2,
    )
    row(
        Z_PK=7000,
        Z_ENT=37,
        ZGID="invented-income",
        ZAMOUNT1=2,
        ZDATE1=100,
        ZDESC2="Invented income",
        ZACCOUNT2=5309,
        ZPAYEE2=6000,
        ZORIGINALAMOUNT=2,
        ZORIGINALCURRENCY="EUR",
        ZRECONCILED=0,
        ZSTATUS1=1,
        ZFLAGS1=0,
    )
    row(
        Z_PK=7001,
        Z_ENT=46,
        ZGID="invented-invalid-transfer",
        ZAMOUNT1=-1,
        ZDATE1=200,
        ZDESC2="Intentional unreadable transfer",
        ZACCOUNT2=5309,
        ZORIGINALAMOUNT=-1,
        ZORIGINALCURRENCY="EUR",
        ZRECONCILED=0,
        ZSTATUS1=1,
        ZFLAGS1=0,
    )
print(store)
