"""End-to-end W10 plans and writes through the installed MoneyWiz Tools CLI."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from test_native_transfer_recipient import _fixture, _transfer_rows
from test_native_transaction_create import W01Runtime, w01_runtime
from test_transaction_create import request as envelope
from write_plan import validate_result


def test_installed_cli_reassigns_linked_transfer_recipient(
    w01_runtime: W01Runtime, tmp_path: Path,
) -> None:
    configured = os.environ.get("MONEYWIZ_TEST_BUNDLE_PATH")
    if not configured:
        pytest.skip("set MONEYWIZ_TEST_BUNDLE_PATH for installed W10 CLI evidence")
    launcher = Path(configured).expanduser().resolve() / "Contents/Resources/runtime/moneywiz.sh"
    assert launcher.is_file() and os.access(launcher, os.X_OK)

    store, identity = _fixture(w01_runtime, tmp_path)
    value = envelope()
    value.update(
        plan_id="w10-installed-cli",
        owner_uri=identity["owner_uri"],
        store_identity={"store_uuid": identity["store_uuid"]},
        app_identity=w01_runtime.app_identity,
        expected_account_gid="w10-source",
        expected_cached_account_balance="700",
        currency_unit="GBP",
        previous_destination_account={
            "account_gid": "w10-previous", "currency_unit": "GBP",
            "expected_cached_balance": "350",
        },
        destination_account={
            "account_gid": "w10-destination", "currency_unit": "GBP",
            "expected_cached_balance": "20",
        },
        operation={
            "operation_id": "w10-installed-operation",
            "kind": "reassign_transfer_recipient",
            "expected_pair": identity["expected_pair"],
        },
    )
    request_path = tmp_path / "request.json"
    plan_path = tmp_path / "plan.json"
    request_path.write_text(json.dumps(value), encoding="utf-8")
    environment = dict(w01_runtime.environment)
    environment.update(
        MONEYWIZ_APP=str(w01_runtime.app),
        MONEYWIZ_MODEL_PATH=str(w01_runtime.model),
        MONEYWIZ_JOURNAL_DIR=str(tmp_path / "journal"),
    )

    planned = subprocess.run(
        [str(launcher), "--db", str(store), "transaction",
         "reassign-transfer-recipient", "--request", str(request_path),
         "--plan", str(plan_path)],
        cwd=tmp_path, env=environment, capture_output=True, text=True, check=False,
    )
    assert planned.returncode == 0, planned.stderr
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert json.loads(planned.stdout)["plan_digest"] == plan["plan_digest"]

    common = ["--plan", str(plan_path), "--app", str(w01_runtime.app),
              "--model", str(w01_runtime.model), "--owner",
              identity["owner_uri"].rsplit("/p", 1)[1]]
    applied = subprocess.run(
        [str(launcher), "--db", str(store), "write", "apply", *common,
         "--reviewed-digest", plan["plan_digest"], "--apply"],
        cwd=tmp_path, env=environment, capture_output=True, text=True, check=False,
    )
    assert applied.returncode == 0, applied.stderr
    assert validate_result(plan, json.loads(applied.stdout))["classification"] == "applied"
    assert _transfer_rows(store)["w10-recipient"][1] == "w10-destination"

    recovered = subprocess.run(
        [str(launcher), "--db", str(store), "write", "recover", *common],
        cwd=tmp_path, env=environment, capture_output=True, text=True, check=False,
    )
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(plan, json.loads(recovered.stdout))["classification"] == "noop"
