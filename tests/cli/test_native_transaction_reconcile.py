"""W04 native flags on invented, marked model-48 stores only."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from test_native_transaction_create import W01Runtime, _crash, _invoke, _new_store
from test_native_transaction_edit import _inspect
from test_transaction_reconcile import request
from write_plan import compute_digest, validate_plan, validate_result
from write_transactions import build_reconcile_plan

pytest_plugins = ["test_native_transaction_create"]


def _plan(runtime: W01Runtime, identity: dict, *, kind="reconcile_transaction",
          gid="w02-withdraw", entity="WithdrawTransaction", status=1, flags=0) -> dict:
    raw = request(kind)
    raw.update({
        "plan_id": f"w04-{kind}-{gid}",
        "store_identity": {"store_uuid": identity["store_uuid"]},
        "owner_uri": identity["owner_uri"],
        "app_identity": runtime.app_identity,
        "expected_account_gid": "w01-account",
        "expected_cached_account_balance": "0",
    })
    raw["source_scope"].update(
        account_gid="w01-account", verified_balance="0",
        source_count=len(identity["transaction_gids"]),
        parsed_count=len(identity["transaction_gids"]),
        transaction_gids=identity["transaction_gids"],
    )
    raw["operations"][0].update(
        transaction_gid=gid, transaction_entity=entity,
        account_gid="w01-account", expected_native_status=status,
        expected_native_flags=flags,
    )
    return build_reconcile_plan(raw, kind=kind)


@pytest.mark.parametrize("kind,gid,flags", [
    ("reconcile_transaction", "w02-withdraw", 0),
    ("reconcile_transaction", "w02-flagged", 1),
    ("unreconcile_transaction", "w02-reconciled", 0),
])
def test_changes_only_reconciled_flag_and_replays_noop(
    w01_runtime: W01Runtime, tmp_path: Path, kind: str, gid: str, flags: int
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, identity, kind=kind, gid=gid, flags=flags)
    before = _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", gid)
    applied = _invoke(w01_runtime, store, plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(plan, json.loads(applied.stdout))["classification"] == "applied"
    after = _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", gid)
    assert after["attributes"]["reconciled"] == (kind == "reconcile_transaction")
    for key in before["attributes"].keys() - {"reconciled"}:
        assert after["attributes"][key] == before["attributes"][key]
    assert after["relationships"] == before["relationships"]
    assert after["account_balance"] == before["account_balance"]
    repeated = _invoke(w01_runtime, store, plan, tmp_path)
    assert repeated.returncode == 0, repeated.stderr
    assert validate_result(plan, json.loads(repeated.stdout))["classification"] == "noop"


def test_stale_scope_or_native_flags_refuses_all_mutation(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    for mutate in (
        lambda p: p["source_scope"].update(transaction_gids=["w02-withdraw"], source_count=1, parsed_count=1),
        lambda p: p["operations"][0].update(expected_native_flags=1),
    ):
        plan = _plan(w01_runtime, identity)
        mutate(plan)
        plan["operations"][0]["expected_postcondition"].update(
            native_status=plan["operations"][0]["expected_native_status"],
            native_flags=plan["operations"][0]["expected_native_flags"],
        )
        plan["plan_digest"] = compute_digest(plan)
        validate_plan(plan)
        before = _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-withdraw")
        rejected = _invoke(w01_runtime, store, plan, tmp_path)
        assert rejected.returncode != 0
        assert _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-withdraw") == before


def test_batch_is_atomic_when_one_target_has_stale_flags(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, identity)
    second = deepcopy(plan["operations"][0])
    second.update(operation_id="w04-2", transaction_gid="w02-flagged", expected_native_flags=0)
    second["expected_postcondition"]["native_flags"] = 0
    plan["operations"].append(second)
    plan["plan_digest"] = compute_digest(plan)
    validate_plan(plan)
    before = _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-withdraw")
    rejected = _invoke(w01_runtime, store, plan, tmp_path)
    assert rejected.returncode != 0
    assert _inspect(w01_runtime, store, tmp_path, "WithdrawTransaction", "w02-withdraw") == before


def test_mixed_persisted_batch_refuses_replay(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    first = _plan(w01_runtime, identity)
    batch = deepcopy(first)
    batch["plan_id"] = "w04-mixed-batch"
    second = deepcopy(batch["operations"][0])
    second.update(operation_id="w04-2", transaction_gid="w02-deposit",
                  transaction_entity="DepositTransaction")
    batch["operations"].append(second)
    batch["plan_digest"] = compute_digest(batch)
    validate_plan(batch)
    applied = _invoke(w01_runtime, store, first, tmp_path)
    assert applied.returncode == 0, applied.stderr
    before = _inspect(w01_runtime, store, tmp_path, "DepositTransaction", "w02-deposit")
    recovered = _invoke(w01_runtime, store, batch, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout)["classification"] == "unknown"
    refused = _invoke(w01_runtime, store, batch, tmp_path)
    assert refused.returncode != 0
    assert _inspect(w01_runtime, store, tmp_path, "DepositTransaction", "w02-deposit") == before


@pytest.mark.parametrize("point,expected", [("--crash-before-save", "retry_safe"),
                                            ("--crash-after-save", "noop")])
def test_crash_recovery_classifies_exact_batch_state(
    w01_runtime: W01Runtime, tmp_path: Path, point: str, expected: str
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, identity)
    crashed = _crash(w01_runtime, store, plan, tmp_path, point)
    assert crashed.returncode in (86, 87), crashed.stderr
    recovered = _invoke(w01_runtime, store, plan, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout)["classification"] == expected
