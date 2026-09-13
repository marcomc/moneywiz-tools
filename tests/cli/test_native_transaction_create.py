"""Production-host W01 coverage using a newly constructed model-48 store."""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import writer_client
from test_transaction_create import request
from write_journal import JournalPaths, JournalStore
from write_plan import compute_digest, validate_plan, validate_result
from write_transactions import build_plan
from writer_client import WriterClient, WriterClientError


@dataclass(frozen=True)
class W01Runtime:
    app: Path
    model: Path
    host: Path
    fixture_builder: Path
    environment: dict[str, str]
    app_identity: dict[str, str]


def _installed_app() -> Path:
    configured = os.environ.get("MONEYWIZ_TEST_APP_PATH")
    app = (
        Path(configured).expanduser()
        if configured
        else Path("/Applications/MoneyWiz.app")
    )
    if not app.is_dir():
        pytest.skip("installed MoneyWiz TestFlight app is unavailable")
    return app.resolve()


def _installed_model(app: Path) -> Path:
    configured = os.environ.get("MONEYWIZ_TEST_MODEL_PATH")
    if configured:
        model = Path(configured).expanduser().resolve()
    else:
        model_directory = app / "Contents/Resources/MoneyWizDataModel.momd"
        with (model_directory / "VersionInfo.plist").open("rb") as source:
            version = plistlib.load(source)["NSManagedObjectModel_CurrentVersionName"]
        model = model_directory / f"{version}.mom"
    if not model.is_file() or app not in model.parents:
        pytest.skip("installed current MoneyWiz model is unavailable inside the app")
    return model


def _compile(arguments: list[str]) -> None:
    completed = subprocess.run(
        arguments,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.fixture(scope="module")
def w01_runtime(tmp_path_factory: pytest.TempPathFactory) -> W01Runtime:
    app = _installed_app()
    model = _installed_model(app)
    directory = tmp_path_factory.mktemp("w01-production-host")

    configured_bundle = os.environ.get("MONEYWIZ_TEST_BUNDLE_PATH")
    if configured_bundle:
        host = (
            Path(configured_bundle).expanduser().resolve()
            / "Contents/MacOS/MoneyWizTools"
        )
        assert host.is_file() and os.access(host, os.X_OK), (
            "MONEYWIZ_TEST_BUNDLE_PATH has no executable MoneyWizTools host"
        )
    else:
        host_bundle = directory / "MoneyWiz Tools.app"
        macos = host_bundle / "Contents/MacOS"
        macos.mkdir(parents=True)
        shutil.copy2(
            ROOT / "scripts/MoneyWizTools-Info.plist",
            host_bundle / "Contents/Info.plist",
        )
        host = macos / "MoneyWizTools"
        _compile(
            [
                "swiftc",
                "-parse-as-library",
                str(ROOT / "scripts/moneywiz_tools_host.swift"),
                "-o",
                str(host),
            ]
        )

    fixture_builder = directory / "MoneyWizW01Fixture"
    _compile(
        [
            "swiftc",
            "-parse-as-library",
            "-D",
            "MONEYWIZ_TOOLS_TESTING",
            str(ROOT / "scripts/moneywiz_tools_host.swift"),
            str(ROOT / "tests/swift/moneywiz_w01_fixture.swift"),
            "-o",
            str(fixture_builder),
        ]
    )

    with (app / "Contents/Info.plist").open("rb") as source:
        info = plistlib.load(source)
    isolated_home = directory / "home"
    isolated_home.mkdir()
    environment = os.environ.copy()
    environment["HOME"] = str(isolated_home)
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    return W01Runtime(
        app=app,
        model=model,
        host=host,
        fixture_builder=fixture_builder,
        environment=environment,
        app_identity={
            "bundle_id": info["CFBundleIdentifier"],
            "version": info["CFBundleShortVersionString"],
            "path": str(app),
            "model_path": str(model),
        },
    )


def _new_store(
    runtime: W01Runtime, tmp_path: Path, *, marked: bool = True
) -> tuple[Path, dict[str, str]]:
    store = tmp_path / "disposable-w01.sqlite"
    arguments = [
        str(runtime.fixture_builder),
        "--store",
        str(store),
        "--model",
        str(runtime.model),
    ]
    if not marked:
        arguments.append("--unmarked")
    completed = subprocess.run(
        arguments,
        cwd=tmp_path,
        env=runtime.environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    identity = json.loads(completed.stdout)
    assert store.is_file()
    return store, identity


def _plan(
    runtime: W01Runtime,
    identity: dict[str, str],
    *,
    kind: str = "create_income",
    amount: str = "2",
    source_event: str = "w01-event",
    expected_balance: str = "0",
) -> dict:
    payload = request(kind)
    operation = payload["operation"]
    payload.update(
        {
            "plan_id": f"plan-{source_event}-{kind}",
            "store_identity": {"store_uuid": identity["store_uuid"]},
            "owner_uri": identity["owner_uri"],
            "app_identity": runtime.app_identity,
            "source_event_id": source_event,
            "expected_account_gid": "w01-account",
            "expected_cached_account_balance": expected_balance,
        }
    )
    operation.update(
        {
            "operation_id": f"operation-{source_event}",
            "account_gid": "w01-account",
            "amount": amount,
            "payee_gid": "w01-payee",
            "category_splits": [
                {
                    "category_gid": (
                        "w01-income-category"
                        if kind == "create_income"
                        else "w01-category"
                    ),
                    "amount": amount,
                }
            ],
            "tag_gids": ["w01-tag"],
            "refund_reference": (
                {
                    "original_transaction_entity": "WithdrawTransaction",
                    "original_transaction_gid": "w01-original",
                }
                if kind == "create_refund"
                else None
            ),
        }
    )
    return build_plan(payload)


def _invoke(
    runtime: W01Runtime,
    store: Path,
    plan: dict,
    tmp_path: Path,
    *,
    recover: bool = False,
) -> subprocess.CompletedProcess[str]:
    suffix = "recover" if recover else "write"
    plan_path = tmp_path / f"{plan['plan_id']}-{suffix}.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return subprocess.run(
        [
            str(runtime.host),
            "--coredata-recover" if recover else "--coredata-write",
            "--store",
            str(store),
            "--model",
            str(runtime.model),
            "--plan",
            str(plan_path),
        ],
        cwd=tmp_path,
        env=runtime.environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _crash(
    runtime: W01Runtime,
    store: Path,
    plan: dict,
    tmp_path: Path,
    crash_flag: str,
) -> subprocess.CompletedProcess[str]:
    plan_path = tmp_path / f"{plan['plan_id']}-crash.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return subprocess.run(
        [
            str(runtime.fixture_builder),
            crash_flag,
            "--store",
            str(store),
            "--model",
            str(runtime.model),
            "--plan",
            str(plan_path),
        ],
        cwd=tmp_path,
        env=runtime.environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("kind", "amount"),
    [
        ("create_income", "2"),
        ("create_income", "0.1"),
        ("create_income", "0.0000001"),
        ("create_expense", "-2"),
        ("create_refund", "2"),
    ],
)
def test_production_host_creates_and_recognizes_w01_transaction(
    w01_runtime: W01Runtime, tmp_path: Path, kind: str, amount: str
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, identity, kind=kind, amount=amount)

    applied = _invoke(w01_runtime, store, plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    applied_receipt = json.loads(applied.stdout)
    assert validate_result(plan, applied_receipt)["classification"] == "applied"

    repeated = _invoke(w01_runtime, store, plan, tmp_path)
    assert repeated.returncode == 0, repeated.stderr
    assert (
        validate_result(plan, json.loads(repeated.stdout))["classification"] == "noop"
    )

    recovered = _invoke(w01_runtime, store, plan, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert (
        validate_result(plan, json.loads(recovered.stdout))["classification"] == "noop"
    )


def test_recovery_before_creation_is_retry_safe_without_invented_identity(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, identity, source_event="absent-recovery")

    recovered = _invoke(w01_runtime, store, plan, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    receipt = validate_result(plan, json.loads(recovered.stdout))
    assert receipt["classification"] == "retry_safe"
    assert receipt["operations"][0]["durable_uri"] is None
    assert receipt["operations"][0]["durable_numeric_id"] is None


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("payee_gid", "missing-payee", "expected one Payee"),
        (
            "category_splits",
            [{"category_gid": "missing-category", "amount": "2"}],
            "expected one Category",
        ),
        ("tag_gids", ["missing-tag"], "expected one Tag"),
    ],
)
def test_creation_rejects_missing_relationship_reference(
    w01_runtime: W01Runtime,
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, identity, source_event=f"missing-{field}")
    plan.pop("plan_digest")
    operation = plan["operations"][0]
    operation[field] = value
    operation["expected_postcondition"][field] = value
    plan = validate_plan(plan)

    completed = _invoke(w01_runtime, store, plan, tmp_path)
    assert completed.returncode == 2
    assert message in completed.stderr

    corrected = _plan(
        w01_runtime,
        identity,
        source_event=f"missing-{field}",
    )
    applied = _invoke(w01_runtime, store, corrected, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(corrected, json.loads(applied.stdout))["classification"] == (
        "applied"
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("payee_gid", "w01-foreign-payee", "Payee owner mismatch"),
        (
            "category_splits",
            [{"category_gid": "w01-foreign-category", "amount": "2"}],
            "Category owner mismatch",
        ),
        ("tag_gids", ["w01-foreign-tag"], "Tag owner mismatch"),
    ],
)
def test_creation_rejects_existing_reference_owned_by_another_user(
    w01_runtime: W01Runtime,
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    source_event = f"foreign-{field}"
    plan = _plan(w01_runtime, identity, source_event=source_event)
    plan.pop("plan_digest")
    operation = plan["operations"][0]
    operation[field] = value
    operation["expected_postcondition"][field] = value
    plan = validate_plan(plan)

    rejected = _invoke(w01_runtime, store, plan, tmp_path)
    assert rejected.returncode == 2
    assert message in rejected.stderr

    corrected = _plan(w01_runtime, identity, source_event=source_event)
    applied = _invoke(w01_runtime, store, corrected, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(corrected, json.loads(applied.stdout))["classification"] == (
        "applied"
    )


def test_creation_rejects_wrong_owner_and_stale_balance(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    payload = request()
    payload.update(
        {
            "store_identity": {"store_uuid": identity["store_uuid"]},
            "owner_uri": "x-coredata://wrong/User/p999",
            "app_identity": w01_runtime.app_identity,
            "source_event_id": "wrong-owner",
            "expected_account_gid": "w01-account",
            "expected_cached_account_balance": "0",
        }
    )
    payload["operation"].update(
        {
            "account_gid": "w01-account",
            "amount": "2",
            "category_splits": [{"category_gid": "w01-income-category", "amount": "2"}],
            "tag_gids": ["w01-tag"],
        }
    )
    wrong_owner = build_plan(payload)
    rejected_owner = _invoke(w01_runtime, store, wrong_owner, tmp_path)
    assert rejected_owner.returncode == 2
    assert "same-owner" in rejected_owner.stderr

    stale = _plan(
        w01_runtime,
        identity,
        source_event="stale-balance",
        expected_balance="1",
    )
    rejected_stale = _invoke(w01_runtime, store, stale, tmp_path)
    assert rejected_stale.returncode == 2
    assert "balance is stale" in rejected_stale.stderr


@pytest.mark.parametrize("account_gid", ["w01-bank-account", "w01-investment-account"])
def test_creation_rejects_non_cash_account_variants_before_insertion(
    w01_runtime: W01Runtime, tmp_path: Path, account_gid: str
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    source_event = f"unsupported-{account_gid}"
    plan = _plan(w01_runtime, identity, source_event=source_event)
    plan.pop("plan_digest")
    plan["expected_account_gid"] = account_gid
    operation = plan["operations"][0]
    operation["account_gid"] = account_gid
    operation["expected_postcondition"]["account_gid"] = account_gid
    plan = validate_plan(plan)

    rejected = _invoke(w01_runtime, store, plan, tmp_path)
    assert rejected.returncode == 2
    assert "CashAccount" in rejected.stderr

    corrected = _plan(w01_runtime, identity, source_event=source_event)
    applied = _invoke(w01_runtime, store, corrected, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(corrected, json.loads(applied.stdout))["classification"] == (
        "applied"
    )


def test_refund_rejects_missing_original_and_over_refund(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    missing = _plan(
        w01_runtime,
        identity,
        kind="create_refund",
        amount="2",
        source_event="missing-original",
    )
    missing.pop("plan_digest")
    operation = missing["operations"][0]
    operation["refund_reference"]["original_transaction_gid"] = "missing-original"
    operation["expected_postcondition"]["refund_reference"][
        "original_transaction_gid"
    ] = "missing-original"
    missing = validate_plan(missing)
    rejected_missing = _invoke(w01_runtime, store, missing, tmp_path)
    assert rejected_missing.returncode == 2
    assert "expected one WithdrawTransaction" in rejected_missing.stderr

    over = _plan(
        w01_runtime,
        identity,
        kind="create_refund",
        amount="11",
        source_event="over-refund",
    )
    rejected_over = _invoke(w01_runtime, store, over, tmp_path)
    assert rejected_over.returncode == 2
    assert "refund total exceeds" in rejected_over.stderr


def test_refund_rejects_original_from_another_account_before_insertion(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    source_event = "other-account-original"
    plan = _plan(
        w01_runtime,
        identity,
        kind="create_refund",
        source_event=source_event,
    )
    plan.pop("plan_digest")
    reference = {
        "original_transaction_entity": "WithdrawTransaction",
        "original_transaction_gid": "w01-other-original",
    }
    operation = plan["operations"][0]
    operation["refund_reference"] = reference
    operation["expected_postcondition"]["refund_reference"] = reference
    plan = validate_plan(plan)

    rejected = _invoke(w01_runtime, store, plan, tmp_path)
    assert rejected.returncode == 2
    assert "ordinary same-account withdrawal" in rejected.stderr

    corrected = _plan(
        w01_runtime,
        identity,
        kind="create_refund",
        source_event=source_event,
    )
    applied = _invoke(w01_runtime, store, corrected, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(corrected, json.loads(applied.stdout))["classification"] == (
        "applied"
    )


def test_full_refund_is_accepted(w01_runtime: W01Runtime, tmp_path: Path) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _plan(
        w01_runtime,
        identity,
        kind="create_refund",
        amount="10",
        source_event="full-refund",
    )
    applied = _invoke(w01_runtime, store, plan, tmp_path)
    assert applied.returncode == 0, applied.stderr
    assert validate_result(plan, json.loads(applied.stdout))["classification"] == (
        "applied"
    )


def test_changed_plan_for_same_source_identity_is_rejected(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    original = _plan(w01_runtime, identity, source_event="stable-source")
    applied = _invoke(w01_runtime, store, original, tmp_path)
    assert applied.returncode == 0, applied.stderr

    changed = _plan(
        w01_runtime,
        identity,
        amount="3",
        source_event="stable-source",
        expected_balance="-1",
    )
    assert (
        original["operations"][0]["transaction_gid"]
        == changed["operations"][0]["transaction_gid"]
    )
    rejected = _invoke(w01_runtime, store, changed, tmp_path)
    assert rejected.returncode == 2
    assert "persisted decimal differs" in rejected.stderr


def test_unmarked_store_cannot_enter_creation_handler(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path, marked=False)
    plan = _plan(w01_runtime, identity, source_event="unmarked")
    rejected = _invoke(w01_runtime, store, plan, tmp_path)
    assert rejected.returncode == 2
    assert "marked disposable fixture required" in rejected.stderr


def test_cumulative_refund_guard_counts_existing_links(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    first = _plan(
        w01_runtime,
        identity,
        kind="create_refund",
        amount="6",
        source_event="refund-first",
    )
    applied = _invoke(w01_runtime, store, first, tmp_path)
    assert applied.returncode == 0, applied.stderr

    remainder = _plan(
        w01_runtime,
        identity,
        kind="create_refund",
        amount="4",
        source_event="refund-remainder",
        expected_balance="6",
    )
    remainder_applied = _invoke(w01_runtime, store, remainder, tmp_path)
    assert remainder_applied.returncode == 0, remainder_applied.stderr

    excessive = _plan(
        w01_runtime,
        identity,
        kind="create_refund",
        amount="1",
        source_event="refund-excessive",
        expected_balance="10",
    )
    rejected = _invoke(w01_runtime, store, excessive, tmp_path)
    assert rejected.returncode == 2
    assert "refund total exceeds" in rejected.stderr


@pytest.mark.parametrize(
    ("crash_flag", "expected_exit", "classification"),
    [
        ("--crash-before-save", 86, "retry_safe"),
        ("--crash-after-save", 87, "noop"),
    ],
)
@pytest.mark.parametrize("kind", ["create_income", "create_expense", "create_refund"])
def test_w01_crash_boundary_is_classified_by_production_recovery(
    w01_runtime: W01Runtime,
    tmp_path: Path,
    crash_flag: str,
    expected_exit: int,
    classification: str,
    kind: str,
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _plan(
        w01_runtime,
        identity,
        kind=kind,
        amount="-2" if kind == "create_expense" else "2",
        source_event=f"{crash_flag.removeprefix('--')}-{kind}",
    )
    crashed = _crash(w01_runtime, store, plan, tmp_path, crash_flag)
    assert crashed.returncode == expected_exit, crashed.stderr

    recovered = _invoke(w01_runtime, store, plan, tmp_path, recover=True)
    assert recovered.returncode == 0, recovered.stderr
    assert validate_result(plan, json.loads(recovered.stdout))["classification"] == (
        classification
    )


@pytest.mark.parametrize(
    ("target", "invalid_timestamp"),
    [
        ("occurred_at", "2026-09-31T09:30:00+02:00"),
        ("created_at", "2026-02-29T10:00:00+01:00"),
        ("source_interval", "2026-09-13T24:00:00+02:00"),
    ],
)
def test_native_rejects_normalized_invalid_calendar_timestamp_before_mutation(
    w01_runtime: W01Runtime,
    tmp_path: Path,
    target: str,
    invalid_timestamp: str,
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    valid = _plan(w01_runtime, identity, source_event=f"invalid-{target}")
    invalid = json.loads(json.dumps(valid))
    invalid.pop("plan_digest")
    if target == "occurred_at":
        operation = invalid["operations"][0]
        operation["occurred_at"] = invalid_timestamp
        operation["expected_postcondition"]["occurred_at"] = invalid_timestamp
    elif target == "created_at":
        invalid["created_at"] = invalid_timestamp
    else:
        invalid["source_interval"]["start"] = invalid_timestamp
    invalid["plan_digest"] = compute_digest(invalid)

    rejected = _invoke(w01_runtime, store, invalid, tmp_path)
    assert rejected.returncode == 2
    assert "timestamp" in rejected.stderr

    recovery = _invoke(w01_runtime, store, valid, tmp_path, recover=True)
    assert recovery.returncode == 0, recovery.stderr
    assert validate_result(valid, json.loads(recovery.stdout))["classification"] == (
        "retry_safe"
    )


def _journal_client(
    runtime: W01Runtime, store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[WriterClient, JournalStore]:
    isolated_home = tmp_path / "writer-home"
    isolated_home.mkdir()
    monkeypatch.setenv("HOME", str(isolated_home))
    monkeypatch.setattr(writer_client, "require_moneywiz_stopped", lambda: None)
    journal = JournalStore(
        JournalPaths.from_environ({"MONEYWIZ_JOURNAL_DIR": str(tmp_path / "journal")})
    )
    return WriterClient(runtime.fixture_builder, runtime.model, store), journal


def test_lost_after_save_response_recovers_journal_without_duplicate(
    w01_runtime: W01Runtime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, identity, source_event="journal-after-save")
    client, journal = _journal_client(w01_runtime, store, tmp_path, monkeypatch)
    monkeypatch.setenv("MONEYWIZ_TEST_CRASH_POINT", "after-save")

    with pytest.raises(WriterClientError, match="unknown"):
        client.apply(plan, plan["plan_digest"], journal)
    assert journal.load(plan["plan_id"])["state"] == "unresolved"

    monkeypatch.delenv("MONEYWIZ_TEST_CRASH_POINT")
    recovered = client.apply(plan, plan["plan_digest"], journal)
    assert recovered["classification"] == "noop"
    assert recovered["verified"] is True
    assert journal.load(plan["plan_id"])["state"] == "verified"


def test_before_save_crash_is_retry_safe_then_journal_can_apply(
    w01_runtime: W01Runtime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, identity = _new_store(w01_runtime, tmp_path)
    plan = _plan(w01_runtime, identity, source_event="journal-before-save")
    client, journal = _journal_client(w01_runtime, store, tmp_path, monkeypatch)
    monkeypatch.setenv("MONEYWIZ_TEST_CRASH_POINT", "before-save")

    with pytest.raises(WriterClientError, match="unknown"):
        client.apply(plan, plan["plan_digest"], journal)
    assert journal.load(plan["plan_id"])["state"] == "unresolved"

    monkeypatch.delenv("MONEYWIZ_TEST_CRASH_POINT")
    recovered = client.recover(plan, journal)
    assert recovered["classification"] == "retry_safe"
    operation = recovered["operations"][0]
    assert operation["durable_uri"] is None
    assert operation["durable_numeric_id"] is None
    assert journal.load(plan["plan_id"])["state"] == "unresolved"

    applied = client.apply(plan, plan["plan_digest"], journal)
    assert applied["classification"] == "applied"
    assert applied["verified"] is True
    assert journal.load(plan["plan_id"])["state"] == "verified"
