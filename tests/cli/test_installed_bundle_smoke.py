"""Opt-in smoke coverage for a real installed MoneyWiz Tools bundle."""

from __future__ import annotations

import base64
import json
import os
import plistlib
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

BUNDLE_ENV = "MONEYWIZ_TEST_BUNDLE_PATH"
MODEL_ENV = "MONEYWIZ_TEST_MODEL_PATH"


@pytest.fixture
def installed_bundle() -> tuple[Path, Path, Path]:
    configured = os.environ.get(BUNDLE_ENV)
    if not configured:
        pytest.skip(f"set {BUNDLE_ENV} to an installed MoneyWiz Tools.app")

    bundle = Path(configured).expanduser().resolve()
    launcher = bundle / "Contents/Resources/runtime/moneywiz.sh"
    bundled_python = bundle / "Contents/Resources/runtime/python/venv/bin/python"
    native_host = bundle / "Contents/MacOS/MoneyWizTools"
    assert bundle.is_dir(), f"{BUNDLE_ENV} is not an app bundle: {bundle}"
    for executable in (launcher, bundled_python, native_host):
        assert executable.is_file(), (
            f"installed bundle payload is missing: {executable}"
        )
        assert os.access(executable, os.X_OK), (
            f"installed bundle payload is not executable: {executable}"
        )
    return bundle, launcher, native_host


def isolated_runtime(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    unrelated_cwd = tmp_path / "unrelated working directory"
    isolated_home = tmp_path / "isolated-home"
    unrelated_cwd.mkdir()
    isolated_home.mkdir()
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    environment["HOME"] = str(isolated_home)
    environment["XDG_CONFIG_HOME"] = str(isolated_home / ".config")
    environment["XDG_DATA_HOME"] = str(isolated_home / ".local/share")
    return unrelated_cwd, environment


def assert_bounded_read_error(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr)["message"] == (
        "Read failed; check database, schema and command arguments"
    )
    assert "Traceback" not in result.stderr


def add_nonfinite_holding(store: Path) -> None:
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
            VALUES (12,24,0,'nonfinite-holding',10,0,?,?, 'SYN',NULL,
                    'Synthetic holding',0,0,0)
            """,
            (float("inf"), 1),
        )


def replace_with_cross_owner_transfer_pair(store: Path) -> None:
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
            INSERT INTO ZSYNCOBJECT
              (Z_PK,Z_ENT,ZOBJECTCREATIONDATE,ZGID,ZRECONCILED,ZAMOUNT1,ZDESC2,
               ZDATE1,ZACCOUNT2,ZSENDERACCOUNT,ZSENDERTRANSACTION,ZORIGINALAMOUNT,
               ZORIGINALCURRENCY,ZORIGINALSENDERAMOUNT,ZORIGINALSENDERCURRENCY,
               ZORIGINALEXCHANGERATE,ZSTATUS1,ZFLAGS1)
            VALUES (12,45,0,'synthetic-deposit',1,10,'Synthetic transfer',100,
                    20,10,11,10,'EUR',-10,'EUR',1,1,0);
        """)


def test_installed_bundle_read_contract(
    installed_bundle: tuple[Path, Path, Path], synthetic_store: Path, tmp_path: Path
) -> None:
    bundle, launcher, _native_host = installed_bundle
    unrelated_cwd, environment = isolated_runtime(tmp_path)

    def run(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(launcher), *arguments],
            cwd=unrelated_cwd,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    with (bundle / "Contents/Info.plist").open("rb") as stream:
        version = plistlib.load(stream)["CFBundleShortVersionString"]
    version_result = run("--version")
    assert version_result.returncode == 0, version_result.stderr
    assert version_result.stdout.strip() == f"moneywiz {version}"

    help_result = run("--help")
    assert help_result.returncode == 0, help_result.stderr
    for command in ("identity", "snapshot", "accounts", "holdings", "transactions"):
        assert command in help_result.stdout

    complete = run("--db", str(synthetic_store), "snapshot", "--until", "2001-01-02")
    assert complete.returncode == 0, complete.stderr
    complete_payload = json.loads(complete.stdout)
    assert complete_payload["completeness"]["complete"] is True
    assert [row["id"] for row in complete_payload["transactions"]] == [11]

    diagnostic_commands = (
        ("accounts",),
        ("holdings", "--account", "10"),
        ("transactions", "--account", "10", "--until", "2001-01-02"),
    )
    for arguments in diagnostic_commands:
        result = run(
            "--db",
            str(synthetic_store),
            *arguments,
            "--format",
            "json",
            "--diagnostics",
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["completeness"]["complete"] is True
        assert isinstance(payload["rows"], list)

    malformed_store = tmp_path / "malformed-read-fixture.sqlite"
    shutil.copy2(synthetic_store, malformed_store)
    with sqlite3.connect(malformed_store) as connection:
        connection.execute(
            "UPDATE ZSYNCOBJECT SET ZORIGINALAMOUNT = NULL WHERE Z_PK = 11"
        )
    partial = run("--db", str(malformed_store), "snapshot", "--until", "2001-01-02")
    assert partial.returncode == 3, partial.stderr
    partial_payload = json.loads(partial.stdout)
    assert partial_payload["completeness"]["complete"] is False
    assert partial_payload["transactions"] == []
    transaction_report = partial_payload["completeness"]["managers"]["transactions"]
    assert transaction_report["source_count"] == 1
    assert transaction_report["parsed_count"] == 0

    bounded_error = run(
        "--db", str(synthetic_store), "snapshot", "--until", "9999-12-31"
    )
    assert bounded_error.returncode == 2
    assert bounded_error.stdout == ""
    assert json.loads(bounded_error.stderr) == {
        "status": "error",
        "error": "ValueError",
        "message": "Read failed; check database, schema and command arguments",
    }
    assert "Traceback" not in bounded_error.stderr

    invalid_balance_store = tmp_path / "invalid-balance.sqlite"
    shutil.copy2(synthetic_store, invalid_balance_store)
    with sqlite3.connect(invalid_balance_store) as connection:
        connection.execute(
            "UPDATE ZSYNCOBJECT SET ZBALLANCE = 'private-balance' WHERE Z_PK = 10"
        )
    invalid_balance = run("--db", str(invalid_balance_store), "snapshot")
    assert_bounded_read_error(invalid_balance)
    assert "private-balance" not in invalid_balance.stderr

    invalid_transaction_store = tmp_path / "invalid-transaction-amount.sqlite"
    shutil.copy2(synthetic_store, invalid_transaction_store)
    with sqlite3.connect(invalid_transaction_store) as connection:
        connection.execute(
            "UPDATE ZSYNCOBJECT SET ZAMOUNT1 = ?, ZORIGINALAMOUNT = ? WHERE Z_PK = 11",
            (float("inf"), float("inf")),
        )
    invalid_transaction = run(
        "--db", str(invalid_transaction_store), "transactions", "--format", "json"
    )
    assert_bounded_read_error(invalid_transaction)

    invalid_holding_store = tmp_path / "invalid-holding-quantity.sqlite"
    shutil.copy2(synthetic_store, invalid_holding_store)
    add_nonfinite_holding(invalid_holding_store)
    invalid_holding = run(
        "--db",
        str(invalid_holding_store),
        "holdings",
        "--account",
        "10",
        "--format",
        "json",
    )
    assert_bounded_read_error(invalid_holding)

    pair_store = tmp_path / "cross-owner-pair.sqlite"
    shutil.copy2(synthetic_store, pair_store)
    replace_with_cross_owner_transfer_pair(pair_store)
    pair = run("--db", str(pair_store), "snapshot", "--account", "20")
    assert pair.returncode == 0, pair.stderr
    pair_payload = json.loads(pair.stdout)
    assert [row["id"] for row in pair_payload["transactions"]] == [12]
    assert pair_payload["audit"] == [{"kind": "cross_owner_transfer", "ids": [11, 12]}]

    with sqlite3.connect(pair_store) as connection:
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
    fee_adjusted_pair = run("--db", str(pair_store), "snapshot")
    assert fee_adjusted_pair.returncode == 0, fee_adjusted_pair.stderr
    assert json.loads(fee_adjusted_pair.stdout)["audit"] == [
        {"kind": "cross_owner_transfer", "ids": [11, 12]}
    ]

    with sqlite3.connect(pair_store) as connection:
        connection.executescript(
            """
            UPDATE ZSYNCOBJECT
            SET ZAMOUNT1 = -1,
                ZORIGINALAMOUNT = -1,
                ZORIGINALCURRENCY = 'BTC',
                ZORIGINALRECIPIENTAMOUNT = 1,
                ZORIGINALRECIPIENTCURRENCY = 'BTC',
                ZORIGINALEXCHANGERATE = 1
            WHERE Z_PK = 11;
            UPDATE ZSYNCOBJECT
            SET ZAMOUNT1 = 1.0009,
                ZORIGINALAMOUNT = 1.0009,
                ZORIGINALCURRENCY = 'BTC',
                ZORIGINALSENDERAMOUNT = -1.0009,
                ZORIGINALSENDERCURRENCY = 'BTC',
                ZORIGINALFEE = NULL,
                ZORIGINALFEECURRENCY = NULL,
                ZORIGINALEXCHANGERATE = 1
            WHERE Z_PK = 12;
            """
        )
    mismatched_pair = run("--db", str(pair_store), "snapshot")
    assert mismatched_pair.returncode == 0, mismatched_pair.stderr
    assert [item["kind"] for item in json.loads(mismatched_pair.stdout)["audit"]] == [
        "cross_owner_transfer",
        "mismatched_transfer_fx",
    ]

    binary_description_store = tmp_path / "binary-description.sqlite"
    shutil.copy2(synthetic_store, binary_description_store)
    with sqlite3.connect(binary_description_store) as connection:
        connection.execute(
            "UPDATE ZSYNCOBJECT SET ZDESC2 = ? WHERE Z_PK = 11",
            (sqlite3.Binary(b"private-description"),),
        )
    for output_format in ("table", "json"):
        binary_description = run(
            "--db",
            str(binary_description_store),
            "transactions",
            "--format",
            output_format,
        )
        assert_bounded_read_error(binary_description)
        assert "private-description" not in binary_description.stderr

    malformed_flags_store = tmp_path / "malformed-native-flags.sqlite"
    shutil.copy2(synthetic_store, malformed_flags_store)
    with sqlite3.connect(malformed_flags_store) as connection:
        connection.execute(
            "UPDATE ZSYNCOBJECT SET ZFLAGS1 = 'private-flags' WHERE Z_PK = 11"
        )
    malformed_flags = run("--db", str(malformed_flags_store), "snapshot")
    assert_bounded_read_error(malformed_flags)
    assert "private-flags" not in malformed_flags.stderr


def test_installed_native_host_missing_model_is_bounded(
    installed_bundle: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    _bundle, _launcher, native_host = installed_bundle
    unrelated_cwd, environment = isolated_runtime(tmp_path)
    missing_model = tmp_path / "missing-model.mom"

    result = subprocess.run(
        [str(native_host), "--model-checksum", str(missing_model)],
        cwd=unrelated_cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "error: cannot load managed-object model\n"
    assert "Traceback" not in result.stderr


def test_installed_native_host_reads_explicit_model_checksum(
    installed_bundle: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    configured = os.environ.get(MODEL_ENV)
    if not configured:
        pytest.skip(f"set {MODEL_ENV} to a valid compiled MoneyWiz model")

    _bundle, _launcher, native_host = installed_bundle
    model = Path(configured).expanduser().resolve()
    assert model.is_file(), f"{MODEL_ENV} is not a compiled model: {model}"
    unrelated_cwd, environment = isolated_runtime(tmp_path)

    result = subprocess.run(
        [str(native_host), "--model-checksum", str(model)],
        cwd=unrelated_cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    checksum = result.stdout.strip()
    assert len(base64.b64decode(checksum, validate=True)) == 32
