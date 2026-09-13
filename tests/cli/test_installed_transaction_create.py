"""Exercise installed W01 planning, journaled apply and P0 readback end to end."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest
from test_native_transaction_create import _new_store, _plan, w01_runtime
from write_transactions import _ENVELOPE_FIELDS, _OPERATION_FIELDS

__all__ = ["w01_runtime"]  # Register the shared native fixture for this module.


@pytest.mark.parametrize("kind", ["create_income", "create_expense", "create_refund"])
def test_installed_creation_cli_and_journal(
    w01_runtime, tmp_path: Path, kind: str
) -> None:
    configured = os.environ.get("MONEYWIZ_TEST_BUNDLE_PATH")
    if not configured:
        pytest.skip("set MONEYWIZ_TEST_BUNDLE_PATH for installed CLI evidence")
    bundle = Path(configured).resolve()
    launcher = bundle / "Contents/Resources/runtime/moneywiz.sh"
    store, identity = _new_store(w01_runtime, tmp_path)
    expected = _plan(
        w01_runtime,
        identity,
        kind=kind,
        amount="-2" if kind == "create_expense" else "2",
    )
    request = {key: expected[key] for key in _ENVELOPE_FIELDS}
    request["operation"] = {
        key: expected["operations"][0][key] for key in _OPERATION_FIELDS
    }
    request_file, plan_file = tmp_path / "request.json", tmp_path / "plan.json"
    request_file.write_text(json.dumps(request))
    environment = dict(w01_runtime.environment)
    environment["MONEYWIZ_JOURNAL_DIR"] = str(tmp_path / "journal")
    for name in ("MONEYWIZ_TOOLS_HOST", "MONEYWIZ_CORE_DATA_WRITER"):
        environment.pop(name, None)

    def run(*arguments: str, expected_exit: int = 0) -> dict:
        completed = subprocess.run(
            [str(launcher), "--db", str(store), *arguments],
            env=environment,
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == expected_exit, completed.stderr
        return json.loads(completed.stdout)

    planned = run(
        "transaction",
        "create",
        "--request",
        str(request_file),
        "--plan",
        str(plan_file),
    )
    assert planned["plan_digest"] == expected["plan_digest"]
    assert not (tmp_path / "journal").exists()
    validated = run("write", "validate", "--plan", str(plan_file))
    assert validated["plan_digest"] == expected["plan_digest"]
    common = (
        "--plan",
        str(plan_file),
        "--app",
        str(w01_runtime.app),
        "--model",
        str(w01_runtime.model),
        "--owner",
        identity["owner_uri"].rsplit("/p", 1)[1],
    )
    apply = (
        "write",
        "apply",
        *common,
        "--reviewed-digest",
        expected["plan_digest"],
        "--apply",
    )
    result = run(*apply)
    assert result["classification"] == "applied"
    for repeated in (run(*apply), run("write", "recover", *common)):
        assert repeated["classification"] == "noop"
        assert (
            repeated["operations"][0]["durable_uri"]
            == result["operations"][0]["durable_uri"]
        )
    entries = run("write", "journal")["entries"]
    assert len(entries) == 1 and entries[0]["state"] == "verified"
    assert run("write", "cleanup")["eligible"] == []
    snapshots = list((tmp_path / "journal/backups").rglob("*.sqlite"))
    assert len(snapshots) == 1
    assert snapshots[0].stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(f"{store.as_uri()}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT Z_PK FROM ZSYNCOBJECT WHERE ZGID=?",
            (expected["operations"][0]["transaction_gid"],),
        ).fetchall()
        assert len(rows) == 1
    snapshot = run("snapshot", expected_exit=3)
    # The intentionally pinned API recognizes the direct tag table but treats
    # the new model's unrelated tag tables as ambiguous. Preserve that diagnostic.
    completeness = snapshot["completeness"]
    assert completeness["complete"] is False
    transactions = completeness["managers"]["transactions"]
    assert transactions["source_count"] == transactions["parsed_count"]
    assert transactions["parsed_count"] >= 2
    assert transactions["relationships"]["transaction_tags"]["storage"] == "unknown"
    assert int(result["operations"][0]["durable_numeric_id"]) in [
        row["id"] for row in snapshot["transactions"]
    ]
