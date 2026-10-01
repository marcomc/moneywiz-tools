"""Relocated bundle plans and recovers W06 on an invented store."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from test_native_delete_adjustment import _plan, _request, _store, _target_count
from test_native_transaction_create import W01Runtime, w01_runtime


def test_relocated_bundle_deletes_guarded_adjustment(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    configured = os.environ.get("MONEYWIZ_TEST_BUNDLE_PATH")
    if not configured:
        pytest.skip("set MONEYWIZ_TEST_BUNDLE_PATH for installed W06 evidence")
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

    store, identity = _store(w01_runtime, tmp_path)
    expected = _plan(w01_runtime, identity)
    request_file, plan_file = tmp_path / "w06-request.json", tmp_path / "w06-plan.json"
    request_file.write_text(json.dumps(_request(w01_runtime, identity)), encoding="utf-8")
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

    planned = run("transaction", "delete-adjustment", "--request", str(request_file),
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
    assert _target_count(store) == 0
    assert run(*apply)["classification"] == "noop"
    assert run("write", "recover", *common)["classification"] == "noop"
