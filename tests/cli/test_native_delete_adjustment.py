"""Production W06 host deletes one guarded adjustment on an invented store."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from test_delete_adjustment import request
from test_native_transaction_create import W01Runtime, w01_runtime
from write_plan import validate_result
from write_transactions import build_delete_adjustment_plan


def _store(
    runtime: W01Runtime, tmp_path: Path, *, marked: bool = True, linked: bool = False
) -> tuple[Path, dict]:
    store = tmp_path / "w06-disposable.sqlite"
    mode = "--w06-linked" if linked else "--w06" if marked else "--w06-unmarked"
    result = subprocess.run(
        [str(runtime.fixture_builder), "--store", str(store),
         "--model", str(runtime.model), mode],
        cwd=tmp_path, env=runtime.environment,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return store, json.loads(result.stdout)


def _request(runtime: W01Runtime, identity: dict) -> dict:
    payload = request()
    payload.update(
        plan_id="w06-invented-store-plan",
        store_identity={"store_uuid": identity["store_uuid"]},
        owner_uri=identity["owner_uri"],
        app_identity=runtime.app_identity,
        timezone="UTC",
        source_event_id="w06-invented-adjustment",
        expected_account_gid="w06-investment",
    )
    payload["operation"].update(
        transaction_gid="w06-target",
        transaction_numeric_id=identity["target_numeric_id"],
        account_gid="w06-investment",
        expected_amount="-2",
        expected_reconcile_amount="108",
        expected_prior_balance="108",
        occurred_at=identity["target_date"],
    )
    return payload


def _plan(runtime: W01Runtime, identity: dict) -> dict:
    return build_delete_adjustment_plan(_request(runtime, identity))


def _invoke(
    runtime: W01Runtime, store: Path, plan: dict, tmp_path: Path, *,
    recover: bool = False, crash: str | None = None, direct: bool = False,
) -> subprocess.CompletedProcess[str]:
    plan_file = tmp_path / "w06-plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    host = runtime.fixture_builder if crash or direct else runtime.host
    environment = dict(runtime.environment)
    if crash is not None:
        environment["MONEYWIZ_TEST_CRASH_POINT"] = crash
    return subprocess.run(
        [str(host), "--coredata-recover" if recover else "--coredata-write",
         "--store", str(store), "--model", str(runtime.model),
         "--plan", str(plan_file)],
        cwd=tmp_path, env=environment, capture_output=True, text=True, check=False,
    )


def _target_count(store: Path) -> int:
    with sqlite3.connect(f"{store.as_uri()}?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        return connection.execute(
            "SELECT COUNT(*) FROM ZSYNCOBJECT WHERE ZGID='w06-target'"
        ).fetchone()[0]


def test_w06_deletes_latest_adjustment_and_replays_noop(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, identity)
    initial = _invoke(w01_runtime, store, plan, tmp_path, recover=True)
    assert initial.returncode == 0, initial.stderr
    assert validate_result(plan, json.loads(initial.stdout))["classification"] == "retry_safe"
    assert _target_count(store) == 1

    applied = _invoke(w01_runtime, store, plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(plan, json.loads(applied.stdout))["classification"] == "applied"
    assert _target_count(store) == 0

    repeated = _invoke(w01_runtime, store, plan, tmp_path)
    assert repeated.returncode == 0, repeated.stderr
    assert validate_result(plan, json.loads(repeated.stdout))["classification"] == "noop"
    assert _target_count(store) == 0


def test_w06_refuses_unmarked_and_stale_targets(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _store(w01_runtime, tmp_path, marked=False)
    plan = _plan(w01_runtime, identity)
    rejected = _invoke(w01_runtime, store, plan, tmp_path)
    assert rejected.returncode != 0
    assert "marked disposable fixture required" in rejected.stderr
    assert _target_count(store) == 1

    marked_path = tmp_path / "marked"
    marked_path.mkdir()
    marked_store, marked_identity = _store(w01_runtime, marked_path)
    payload = _request(w01_runtime, marked_identity)
    payload["operation"]["expected_amount"] = "-3"
    stale = build_delete_adjustment_plan(payload)
    refused = _invoke(w01_runtime, marked_store, stale, marked_path)
    assert refused.returncode != 0
    assert _target_count(marked_store) == 1


@pytest.mark.parametrize("recover", [False, True])
def test_w06_direct_entrypoints_refuse_unmarked_store(
    w01_runtime: W01Runtime, tmp_path: Path, recover: bool
) -> None:
    store, identity = _store(w01_runtime, tmp_path, marked=False)
    plan = _plan(w01_runtime, identity)
    rejected = _invoke(w01_runtime, store, plan, tmp_path, recover=recover, direct=True)
    assert rejected.returncode != 0
    assert "marked disposable fixture required" in rejected.stderr
    assert _target_count(store) == 1


def test_w06_refuses_target_with_dependent_relationship(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _store(w01_runtime, tmp_path, linked=True)
    plan = _plan(w01_runtime, identity)
    refused = _invoke(w01_runtime, store, plan, tmp_path)
    assert refused.returncode != 0
    assert "unsupported or ambiguous" in refused.stderr or "dependent relationship" in refused.stderr
    assert _target_count(store) == 1


@pytest.mark.parametrize(
    ("crash", "expected"),
    [("before-save", "retry_safe"), ("after-save", "noop")],
)
def test_w06_crash_boundary_recovers_without_duplicate_deletion(
    w01_runtime: W01Runtime, tmp_path: Path, crash: str, expected: str
) -> None:
    store, identity = _store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, identity)
    interrupted = _invoke(w01_runtime, store, plan, tmp_path, crash=crash)
    assert interrupted.returncode == (86 if crash == "before-save" else 87)
    recovered = _invoke(w01_runtime, store, plan, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(plan, json.loads(recovered.stdout))["classification"] == expected
    assert _target_count(store) == (1 if crash == "before-save" else 0)
