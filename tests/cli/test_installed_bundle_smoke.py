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
