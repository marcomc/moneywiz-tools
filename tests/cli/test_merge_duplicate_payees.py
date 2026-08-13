import csv
import sqlite3
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import merge_duplicate_payees


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
    script = REPO_ROOT / "scripts/merge_duplicate_payees.py"
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
    assert "fuzzy_candidates=not-requested" in result.stdout


@pytest.mark.parametrize(
    "arguments",
    [(), ("--show-plan",), ("--quiet",), ("--apply",)],
)
def test_exact_only_modes_do_not_build_fuzzy_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: tuple[str, ...],
) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)

    def fail_fuzzy_analysis(payees: object) -> None:
        raise AssertionError(f"unexpected fuzzy analysis for {payees!r}")

    monkeypatch.setattr(
        merge_duplicate_payees, "_build_fuzzy_candidates", fail_fuzzy_analysis
    )
    monkeypatch.setattr(
        merge_duplicate_payees, "apply_exact_groups", lambda db, plan: None
    )

    status = merge_duplicate_payees.main(["--db", str(db_path), *arguments])

    captured = capsys.readouterr()
    assert status == 0, captured.err
    assert "fuzzy_candidates=not-requested" in captured.out


def test_empty_merge_apply_checks_blocked_capability_without_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = merge_duplicate_payees.DuplicatePayeePlan(
        payees_analyzed=0, exact_groups=(), fuzzy_candidates=None
    )
    capability_calls: list[tuple[Path, str]] = []

    def reject_capability(db_path: Path, capability: str) -> object:
        capability_calls.append((db_path, capability))
        raise merge_duplicate_payees.ReassignmentError("capability is blocked")

    monkeypatch.setattr(
        merge_duplicate_payees,
        "require_coredata_write_capability",
        reject_capability,
    )
    monkeypatch.setattr(
        merge_duplicate_payees,
        "apply_coredata_payload",
        lambda *_args, **_kwargs: pytest.fail(
            "native host ran for an empty merge apply plan"
        ),
    )

    db_path = Path("store.sqlite")
    with pytest.raises(
        merge_duplicate_payees.ReassignmentError, match="capability is blocked"
    ):
        merge_duplicate_payees.apply_exact_groups(db_path, plan)

    assert capability_calls == [(db_path, "write.merge-duplicate-payees")]


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


def test_explicit_fuzzy_map_builds_candidates_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    map_path = tmp_path / "payee-fuzzy-review.csv"
    make_database(db_path)
    original_builder = merge_duplicate_payees._build_fuzzy_candidates
    calls = 0

    def count_fuzzy_analysis(
        payees: Sequence[merge_duplicate_payees.Payee],
    ) -> tuple[merge_duplicate_payees.FuzzyCandidate, ...]:
        nonlocal calls
        calls += 1
        return original_builder(payees)

    monkeypatch.setattr(
        merge_duplicate_payees, "_build_fuzzy_candidates", count_fuzzy_analysis
    )

    status = merge_duplicate_payees.main(
        ["--db", str(db_path), "--fuzzy-map", str(map_path)]
    )

    captured = capsys.readouterr()
    assert status == 0, captured.err
    assert calls == 1


def test_requested_empty_fuzzy_map_is_distinct_from_not_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    map_path = tmp_path / "payee-fuzzy-review.csv"
    make_database(db_path)
    monkeypatch.setattr(
        merge_duplicate_payees, "_build_fuzzy_candidates", lambda payees: ()
    )

    status = merge_duplicate_payees.main(
        ["--db", str(db_path), "--fuzzy-map", str(map_path)]
    )

    captured = capsys.readouterr()
    assert status == 0, captured.err
    assert "(0 pending candidates)" in captured.out
    assert "fuzzy_candidates=0" in captured.out
    with map_path.open(newline="", encoding="utf-8") as map_file:
        assert list(csv.DictReader(map_file)) == []


def test_fuzzy_candidates_never_cross_user_boundaries() -> None:
    payees = (
        merge_duplicate_payees.Payee(1, "one", "Digital Ocean", 1, 0, 0),
        merge_duplicate_payees.Payee(2, "two", "Digital.Ocean", 2, 0, 0),
        merge_duplicate_payees.Payee(3, "three", "Digitalocean", 1, 0, 0),
    )

    candidates = merge_duplicate_payees._build_fuzzy_candidates(payees)

    assert len(candidates) == 1
    assert candidates[0].user_id == 1
    assert {candidates[0].left.id, candidates[0].right.id} == {1, 3}


def test_existing_fuzzy_map_requires_explicit_overwrite(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    map_path = tmp_path / "payee-fuzzy-review.csv"
    make_database(db_path)
    map_path.write_text("existing review", encoding="utf-8")

    result = run_merge(db_path, "--fuzzy-map", str(map_path))

    assert result.returncode == 2
    assert "already exists" in result.stderr
    assert "Traceback" not in result.stderr


def test_existing_fuzzy_map_is_rejected_before_fuzzy_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    map_path = tmp_path / "payee-fuzzy-review.csv"
    make_database(db_path)
    map_path.write_text("existing review", encoding="utf-8")

    def fail_fuzzy_analysis(payees: object) -> None:
        raise AssertionError(f"unexpected fuzzy analysis for {payees!r}")

    monkeypatch.setattr(
        merge_duplicate_payees, "_build_fuzzy_candidates", fail_fuzzy_analysis
    )

    status = merge_duplicate_payees.main(
        ["--db", str(db_path), "--fuzzy-map", str(map_path)]
    )

    captured = capsys.readouterr()
    assert status == 2
    assert "already exists" in captured.err


@pytest.mark.parametrize(
    ("left_name", "right_name"),
    [
        ("=LEFT()", "+RIGHT()"),
        ("-1", "@RIGHT"),
        ("\t=LEFT()", "\r+RIGHT()"),
        ("\x00-1", "\n@RIGHT"),
        ("\u00a0\u200b\t=LEFT()", "\u202f\u2060\r+RIGHT()"),
        ("\uff1dLEFT()", "\uff0bRIGHT()"),
        ("\u3000\uff0d1", "\u00a0\uff20RIGHT"),
    ],
)
def test_fuzzy_map_writes_hidden_formula_like_names_as_literals(
    tmp_path: Path, left_name: str, right_name: str
) -> None:
    map_path = tmp_path / "payee-fuzzy-review.csv"
    candidate = merge_duplicate_payees.FuzzyCandidate(
        user_id=1,
        left=merge_duplicate_payees.Payee(1, "left", left_name, 1, 0, 0),
        right=merge_duplicate_payees.Payee(2, "right", right_name, 1, 0, 0),
        similarity=0.9,
        reason="test",
    )

    merge_duplicate_payees.write_fuzzy_map(map_path, (candidate,), overwrite=False)

    with map_path.open(newline="", encoding="utf-8") as map_file:
        row = next(csv.DictReader(map_file))
    assert row["left_name"] == f"'{left_name}"
    assert row["right_name"] == f"'{right_name}"


@pytest.mark.parametrize(
    ("left_name", "right_name"),
    [
        ("Merchant A", "Merchant B"),
        (" Merchant A", "\tMerchant B"),
        ("'=LEFT()", "\u200b'\uff0bRIGHT()"),
    ],
)
def test_fuzzy_map_preserves_non_formula_names(
    tmp_path: Path, left_name: str, right_name: str
) -> None:
    map_path = tmp_path / "payee-fuzzy-review.csv"
    candidate = merge_duplicate_payees.FuzzyCandidate(
        user_id=1,
        left=merge_duplicate_payees.Payee(1, "left", left_name, 1, 0, 0),
        right=merge_duplicate_payees.Payee(2, "right", right_name, 1, 0, 0),
        similarity=0.9,
        reason="test",
    )

    merge_duplicate_payees.write_fuzzy_map(map_path, (candidate,), overwrite=False)

    with map_path.open(newline="", encoding="utf-8") as map_file:
        row = next(csv.DictReader(map_file))
    assert row["left_name"] == left_name
    assert row["right_name"] == right_name
