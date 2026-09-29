"""Relocated bundle plans and recovers W07 on an invented store."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from test_native_transaction_create import W01Runtime, w01_runtime
from test_native_transfer import _fixture, _gids, _plan
from write_transactions import _ENVELOPE_FIELDS


def test_relocated_bundle_replaces_import_with_transfer(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    configured = os.environ.get("MONEYWIZ_TEST_BUNDLE_PATH")
    if not configured:
        pytest.skip("set MONEYWIZ_TEST_BUNDLE_PATH for installed W07 evidence")
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
        capture_output=True, check=False,
    )
    assert denied.returncode != 0

    store, identity = _fixture(w01_runtime, tmp_path, "--w07-paired")
    expected = _plan(w01_runtime, tmp_path, identity, paired=True)
    operation = expected["operations"][0]
    request = {key: expected[key] for key in _ENVELOPE_FIELDS}
    request["destination_account"] = expected["destination_account"]
    request["operation"] = {
        key: operation[key] for key in (
            "operation_id", "kind", "source_old", "destination_old", "send_at",
            "receive_at", "sender_amount", "recipient_amount", "exchange_rate",
            "fee_amount",
        )
    }
    request_file, plan_file = tmp_path / "request.json", tmp_path / "installed-plan.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")
    environment = dict(w01_runtime.environment)
    environment["MONEYWIZ_JOURNAL_DIR"] = str(tmp_path / "journal")
    for name in ("PYTHONPATH", "MONEYWIZ_TOOLS_HOST", "MONEYWIZ_CORE_DATA_WRITER"):
        environment.pop(name, None)

    def run(*arguments: str) -> dict:
        completed = subprocess.run(
            [sandbox, "-p", profile, str(launcher), "--db", str(store), *arguments],
            cwd=tmp_path, env=environment, text=True, capture_output=True, check=False,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    planned = run("transaction", "transfer", "--request", str(request_file),
                  "--plan", str(plan_file))
    assert planned["plan_digest"] == expected["plan_digest"]
    assert run("write", "validate", "--plan", str(plan_file))["plan_digest"] == expected["plan_digest"]
    common = (
        "--plan", str(plan_file), "--app", str(w01_runtime.app),
        "--model", str(w01_runtime.model),
        "--owner", identity["owner_uri"].rsplit("/p", 1)[1],
    )
    apply = ("write", "apply", *common, "--reviewed-digest", expected["plan_digest"], "--apply")
    assert run(*apply)["classification"] == "applied"
    gids = _gids(store)
    assert "w07-import-source" not in gids
    assert "w07-import-destination" not in gids
    assert operation["transaction_gid"] in gids
    assert operation["recipient_transaction_gid"] in gids
    assert run(*apply)["classification"] == "noop"
    assert run("write", "recover", *common)["classification"] == "noop"
