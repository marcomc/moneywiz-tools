import csv
import sqlite3
import subprocess
import sys
from pathlib import Path


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
            ZPAYEE2 INTEGER
        );
        CREATE TABLE ZSTRINGHISTORYITEM (
            Z_PK INTEGER PRIMARY KEY,
            ZPAYEE INTEGER
        );
        """
    )
    con.execute("INSERT INTO Z_PRIMARYKEY (Z_ENT, Z_NAME) VALUES (29, 'Payee')")
    con.executemany(
        """
        INSERT INTO ZSYNCOBJECT (Z_PK, Z_ENT, ZGID, ZNAME5, ZUSER7)
        VALUES (?, 29, ?, ?, 1)
        """,
        [
            (200, "payee-ita-uppercase", "ITA"),
            (201, "payee-ita-title", "Ita"),
            (202, "payee-acton-nbsp", "Acton\u00a0Forini"),
            (203, "payee-acton-ascii", "Acton Forini"),
            (300, "payee-digitalocean-space", "Digitalocean Com"),
            (301, "payee-digitalocean-dot", "Digitalocean.Com"),
            (302, "payee-lidl-suffix", "Lidl2"),
        ],
    )
    con.executemany(
        "INSERT INTO ZSYNCOBJECT (Z_PK, Z_ENT, ZPAYEE2) VALUES (?, 40, ?)",
        [
            (400, 200),
            (401, 200),
            (402, 201),
            (403, 202),
            (404, 202),
            (405, 202),
            (406, 203),
        ],
    )
    con.executemany(
        "INSERT INTO ZSTRINGHISTORYITEM (Z_PK, ZPAYEE) VALUES (?, ?)",
        [
            (500, 200),
            (501, 201),
            (502, 201),
            (503, 203),
        ],
    )
    con.commit()
    con.close()


def run_merge(db_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts/merge_duplicate_payees.py"
    return subprocess.run(
        [sys.executable, str(script), "--db", str(db_path), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def test_exact_plan_prefers_readable_ascii_canonical_payee(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)

    result = run_merge(db_path, "--show-plan")

    assert result.returncode == 0, result.stderr
    assert "keep 201 ('Ita'; ZPAYEE2=1, StringHistoryItem=2)" in result.stdout
    assert "merge 200 ('ITA'; ZPAYEE2=2, StringHistoryItem=1)" in result.stdout
    assert "keep 203 ('Acton Forini'; ZPAYEE2=1, StringHistoryItem=1)" in result.stdout
    assert (
        "merge 202 ('Acton\\xa0Forini'; ZPAYEE2=3, StringHistoryItem=0)"
        in result.stdout
    )
    assert "exact_groups=2, merges=2" in result.stdout


def test_fuzzy_map_is_pending_review_only(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    map_path = tmp_path / "payee-fuzzy-review.csv"
    make_database(db_path)

    result = run_merge(db_path, "--quiet", "--fuzzy-map", str(map_path))

    assert result.returncode == 0, result.stderr
    assert "pending candidates" in result.stdout
    with map_path.open(newline="", encoding="utf-8") as map_file:
        rows = list(csv.DictReader(map_file))
    digitalocean = next(
        row for row in rows if {row["left_id"], row["right_id"]} == {"300", "301"}
    )
    assert digitalocean["similarity"] == "1.000"
    assert digitalocean["reason"] == "loose-normalized-equal"
    assert digitalocean["review_decision"] == "pending"
    assert digitalocean["approved_canonical_id"] == ""
    assert not any({row["left_id"], row["right_id"]} == {"201", "302"} for row in rows)


def test_existing_fuzzy_map_requires_explicit_overwrite(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    map_path = tmp_path / "payee-fuzzy-review.csv"
    make_database(db_path)
    map_path.write_text("existing review", encoding="utf-8")

    result = run_merge(db_path, "--fuzzy-map", str(map_path))

    assert result.returncode == 2
    assert "already exists" in result.stderr
    assert "Traceback" not in result.stderr
