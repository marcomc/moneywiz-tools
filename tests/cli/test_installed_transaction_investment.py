"""Installed W08 admission follows the reviewed application edition."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from test_native_investment import new_store, plan
from test_native_transaction_create import W01Runtime, w01_runtime
from write_plan import validate_result


def test_installed_w08_admission_by_edition(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    configured = os.environ.get("MONEYWIZ_TEST_BUNDLE_PATH")
    if not configured:
        pytest.skip("set MONEYWIZ_TEST_BUNDLE_PATH for installed W08 evidence")
    launcher = (Path(configured).resolve()
                / "Contents/Resources/runtime/moneywiz.sh")
    environment = dict(w01_runtime.environment)
    environment["MONEYWIZ_JOURNAL_DIR"] = str(tmp_path / "journal")
    for name in ("PYTHONPATH", "MONEYWIZ_TOOLS_HOST", "MONEYWIZ_CORE_DATA_WRITER"):
        environment.pop(name, None)

    def run(store: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(launcher), "--db", str(store), *arguments],
            cwd=tmp_path, env=environment, capture_output=True, text=True,
            check=False,
        )

    marked_dir = tmp_path / "marked"
    marked_dir.mkdir()
    store, identity = new_store(w01_runtime, marked_dir, units=True)
    expected = plan(w01_runtime, identity, "investment_buy")
    request = {key: expected[key] for key in (
        "plan_id", "profile_id", "model_checksum", "store_identity", "owner_uri",
        "app_identity", "created_at", "timezone", "source_interval",
        "source_evidence_refs", "source_event_id", "expected_account_gid",
        "expected_cached_account_balance", "currency_unit",
    )}
    request["operation"] = {key: expected["operations"][0][key] for key in (
        "operation_id", "kind", "account_gid", "amount", "occurred_at",
        "payee_gid", "category_splits", "tag_gids", "note", "account_mode",
        "cash_event_type", "holding_gid", "holding_symbol", "asset_type",
        "investment_symbol", "quantity", "unit_price", "fee", "fee_currency",
        "expected_prior_cash", "expected_prior_units",
    )}
    request_path, plan_path = tmp_path / "request.json", tmp_path / "plan.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    planned = run(store, "transaction", "investment", "--request",
                  str(request_path), "--plan", str(plan_path))
    assert planned.returncode == 0, planned.stderr
    assert json.loads(planned.stdout)["plan_digest"] == expected["plan_digest"]
    common = ("--plan", str(plan_path), "--app", str(w01_runtime.app),
              "--model", str(w01_runtime.model),
              "--owner", identity["owner_uri"].rsplit("/p", 1)[1])
    apply = ("write", "apply", *common, "--reviewed-digest",
             expected["plan_digest"], "--apply")
    applied = run(store, *apply)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(expected, json.loads(applied.stdout))["classification"] == "applied"
    replay = run(store, *apply)
    assert replay.returncode == 0, replay.stderr
    assert validate_result(expected, json.loads(replay.stdout))["classification"] == "noop"

    unmarked_dir = tmp_path / "unmarked"
    unmarked_dir.mkdir()
    unmarked_store, unmarked_identity = new_store(
        w01_runtime, unmarked_dir, units=False, marked=False
    )
    # The unmarked producer creates an aggregate account without a holding.
    unmarked_plan = plan(w01_runtime, unmarked_identity, "investment_income", aggregate=True)
    unmarked_path = tmp_path / "unmarked-plan.json"
    unmarked_path.write_text(json.dumps(unmarked_plan), encoding="utf-8")
    environment["MONEYWIZ_JOURNAL_DIR"] = str(unmarked_dir / "journal")
    with sqlite3.connect(f"{unmarked_store.as_uri()}?mode=ro", uri=True) as database:
        original_rows = database.execute("SELECT * FROM ZSYNCOBJECT ORDER BY Z_PK").fetchall()
    unmarked_result = run(unmarked_store, "write", "apply", "--plan", str(unmarked_path),
                  "--reviewed-digest", unmarked_plan["plan_digest"], "--apply",
                  "--app", str(w01_runtime.app), "--model", str(w01_runtime.model),
                  "--owner", unmarked_identity["owner_uri"].rsplit("/p", 1)[1])
    if w01_runtime.app_identity["bundle_id"] == "com.moneywiz.personalfinance-setapp":
        assert unmarked_result.returncode == 0, unmarked_result.stderr
        assert validate_result(unmarked_plan, json.loads(unmarked_result.stdout))["classification"] == "applied"
        recovered = run(unmarked_store, "write", "recover", "--plan", str(unmarked_path),
                        "--app", str(w01_runtime.app), "--model", str(w01_runtime.model),
                        "--owner", unmarked_identity["owner_uri"].rsplit("/p", 1)[1])
        assert recovered.returncode == 0, recovered.stderr
        assert validate_result(unmarked_plan, json.loads(recovered.stdout))["classification"] == "noop"
    else:
        assert unmarked_result.returncode == 2
        assert "disposable" in unmarked_result.stderr
        assert not list((unmarked_dir / "journal" / "entries").glob("*.json"))
        with sqlite3.connect(f"{unmarked_store.as_uri()}?mode=ro", uri=True) as database:
            assert database.execute("SELECT * FROM ZSYNCOBJECT ORDER BY Z_PK").fetchall() == original_rows
