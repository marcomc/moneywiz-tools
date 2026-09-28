"""Exercise the packaged W02 CLI on an invented disposable model-48 store."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from test_native_transaction_create import _new_store, w01_runtime
from test_native_transaction_edit import _edit_plan, _inspect
from write_transactions import _ENVELOPE_FIELDS

__all__ = ["w01_runtime"]


def test_relocated_bundle_plans_applies_and_recovers_edit(
    w01_runtime, tmp_path: Path
) -> None:
    configured = os.environ.get("MONEYWIZ_TEST_BUNDLE_PATH")
    if not configured:
        pytest.skip("set MONEYWIZ_TEST_BUNDLE_PATH for installed W02 evidence")
    bundle = Path(configured).resolve()
    relocated = tmp_path / "relocated" / "MoneyWiz Tools.app"
    relocated.parent.mkdir()
    shutil.copytree(bundle, relocated, symlinks=True)
    launcher = relocated / "Contents/Resources/runtime/moneywiz.sh"
    sandbox = shutil.which("sandbox-exec")
    assert sandbox is not None
    source = Path(__file__).resolve().parents[2]
    profile = f'(version 1) (allow default) (deny file-read* (subpath "{source}"))'
    denied = subprocess.run(
        [sandbox, "-p", profile, "/bin/cat", str(source / "README.md")],
        capture_output=True,
        check=False,
    )
    assert denied.returncode != 0

    store, identity = _new_store(w01_runtime, tmp_path)
    before = _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-withdraw")
    expected = _edit_plan(w01_runtime, identity, source_event="installed-w02-edit")
    request = {key: expected[key] for key in _ENVELOPE_FIELDS}
    request["operation"] = {
        key: expected["operations"][0][key]
        for key in (
            "operation_id", "kind", "transaction_entity", "transaction_gid",
            "account_gid", "changes", "expected_prior", "correction_mode",
        )
    }
    request_file, plan_file = tmp_path / "request.json", tmp_path / "plan.json"
    request_file.write_text(json.dumps(request))
    environment = dict(w01_runtime.environment)
    environment["MONEYWIZ_JOURNAL_DIR"] = str(tmp_path / "journal")
    for name in ("PYTHONPATH", "MONEYWIZ_TOOLS_HOST", "MONEYWIZ_CORE_DATA_WRITER"):
        environment.pop(name, None)

    def run(*arguments: str) -> dict:
        completed = subprocess.run(
            [sandbox, "-p", profile, str(launcher), "--db", str(store), *arguments],
            cwd=tmp_path,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    planned = run("transaction", "edit", "--request", str(request_file), "--plan", str(plan_file))
    assert planned["plan_digest"] == expected["plan_digest"]
    assert run("write", "validate", "--plan", str(plan_file))["plan_digest"] == expected["plan_digest"]
    common = (
        "--plan", str(plan_file), "--app", str(w01_runtime.app),
        "--model", str(w01_runtime.model),
        "--owner", identity["owner_uri"].rsplit("/p", 1)[1],
    )
    apply = (
        "write", "apply", *common,
        "--reviewed-digest", expected["plan_digest"], "--apply",
    )
    result = run(*apply)
    assert result["classification"] == "applied"
    assert run(*apply)["classification"] == "noop"
    assert run("write", "recover", *common)["classification"] == "noop"
    after = _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-withdraw")
    assert after["attributes"]["notes"] == "W02 changed note"
    assert after["account_balance"] == before["account_balance"]
    assert after["relationships"] == before["relationships"]
