import plistlib
import re
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import reassign_payees_by_id

TRANSACTION_TYPES = (
    "DepositTransaction",
    "InvestmentExchangeTransaction",
    "InvestmentBuyTransaction",
    "InvestmentSellTransaction",
    "ReconcileTransaction",
    "RefundTransaction",
    "TransferBudgetTransaction",
    "TransferDepositTransaction",
    "TransferWithdrawTransaction",
    "WithdrawTransaction",
)

ACCOUNT_TYPES = (
    "Account",
    "BankChequeAccount",
    "BankSavingAccount",
    "CashAccount",
    "CreditCardAccount",
    "ForexAccount",
    "InvestmentAccount",
    "LoanAccount",
)


def make_database(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER, Z_NAME TEXT);
        CREATE TABLE ZUSER (Z_PK INTEGER PRIMARY KEY);
        CREATE TABLE ZSYNCOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER,
            ZGID TEXT,
            ZNAME5 TEXT,
            ZUSER7 INTEGER,
            ZACCOUNT2 INTEGER,
            ZDESC2 TEXT,
            ZPAYEE2 INTEGER,
            ZUSER INTEGER
        );
        """
    )
    con.executemany(
        "INSERT INTO Z_PRIMARYKEY (Z_ENT, Z_NAME) VALUES (?, ?)",
        [(index + 40, name) for index, name in enumerate(TRANSACTION_TYPES)]
        + [(index + 10, name) for index, name in enumerate(ACCOUNT_TYPES)]
        + [(29, "Payee")],
    )
    withdraw_entity = 40 + TRANSACTION_TYPES.index("WithdrawTransaction")
    con.execute("INSERT INTO ZSYNCOBJECT (Z_PK, Z_ENT, ZUSER) VALUES (100, 10, 1)")
    con.execute("INSERT INTO ZUSER (Z_PK) VALUES (1)")
    con.execute(
        """
        INSERT INTO ZSYNCOBJECT (Z_PK, Z_ENT, ZGID, ZNAME5, ZUSER7)
        VALUES (200, 29, 'payee-existing', 'Vodafone\u00a0Pag\u00a0Ricar\u00a0Au', 1)
        """
    )
    con.executemany(
        """
        INSERT INTO ZSYNCOBJECT
        (Z_PK, Z_ENT, ZGID, ZACCOUNT2, ZDESC2, ZPAYEE2)
        VALUES (?, ?, ?, 100, ?, 999)
        """,
        [
            (300, withdraw_entity, "transaction-existing", " Vodafone Pag Ricar Au "),
            (301, withdraw_entity, "transaction-new-one", "New Merchant"),
            (302, withdraw_entity, "transaction-new-two", "New Merchant"),
        ],
    )
    con.commit()
    con.close()


def run_reassign(db_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts/reassign_payees_by_id.py"
    return subprocess.run(
        [sys.executable, str(script), "--db", str(db_path), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def fake_moneywiz_app(tmp_path: Path) -> Callable[[], tuple[Path, Path, Path]]:
    def create() -> tuple[Path, Path, Path]:
        app = tmp_path / "MoneyWiz 2026.app"
        contents = app / "Contents"
        model_directory = contents / "Resources/MoneyWizDataModel.momd"
        model_directory.mkdir(parents=True)
        with (contents / "Info.plist").open("wb") as info_file:
            plistlib.dump(
                {
                    "CFBundleIdentifier": (
                        reassign_payees_by_id.EXPECTED_BUNDLE_IDENTIFIER
                    )
                },
                info_file,
            )
        with (model_directory / "VersionInfo.plist").open("wb") as version_file:
            plistlib.dump(
                {"NSManagedObjectModel_CurrentVersionName": "MoneyWizDataModel 48"},
                version_file,
            )
        model = model_directory / "MoneyWizDataModel 48.mom"
        model.touch()
        return app, model_directory, model

    return create


def test_resolve_model_accepts_current_extensionless_manifest_leaf(
    fake_moneywiz_app: Callable[[], tuple[Path, Path, Path]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _model_directory, model = fake_moneywiz_app()
    monkeypatch.delenv("MONEYWIZ_MODEL_PATH", raising=False)
    monkeypatch.setenv("MONEYWIZ_APP", str(app))

    assert reassign_payees_by_id._resolve_model() == model


def test_resolve_model_accepts_exact_mom_manifest_leaf_without_appending_twice(
    fake_moneywiz_app: Callable[[], tuple[Path, Path, Path]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, model_directory, model = fake_moneywiz_app()
    with (model_directory / "VersionInfo.plist").open("wb") as version_file:
        plistlib.dump(
            {"NSManagedObjectModel_CurrentVersionName": model.name}, version_file
        )
    monkeypatch.delenv("MONEYWIZ_MODEL_PATH", raising=False)
    monkeypatch.setenv("MONEYWIZ_APP", str(app))

    assert reassign_payees_by_id._resolve_model() == model


@pytest.mark.parametrize(
    "version_name",
    [
        "/tmp/MoneyWizDataModel 48",
        "../MoneyWizDataModel 48",
        "Models/MoneyWizDataModel 48",
        "MoneyWizDataModel 48.momd",
        "MoneyWizDataModel 48.sqlite",
        " MoneyWizDataModel 48",
        "MoneyWizDataModel 48\n",
    ],
)
def test_resolve_model_rejects_invalid_manifest_leaf(
    fake_moneywiz_app: Callable[[], tuple[Path, Path, Path]],
    monkeypatch: pytest.MonkeyPatch,
    version_name: str,
) -> None:
    app, model_directory, _model = fake_moneywiz_app()
    with (model_directory / "VersionInfo.plist").open("wb") as version_file:
        plistlib.dump(
            {"NSManagedObjectModel_CurrentVersionName": version_name}, version_file
        )
    monkeypatch.delenv("MONEYWIZ_MODEL_PATH", raising=False)
    monkeypatch.setenv("MONEYWIZ_APP", str(app))

    with pytest.raises(reassign_payees_by_id.ReassignmentError):
        reassign_payees_by_id._resolve_model()


@pytest.mark.parametrize("model_kind", ["missing", "directory"])
def test_resolve_model_rejects_missing_or_non_file_model(
    fake_moneywiz_app: Callable[[], tuple[Path, Path, Path]],
    monkeypatch: pytest.MonkeyPatch,
    model_kind: str,
) -> None:
    app, _model_directory, model = fake_moneywiz_app()
    model.unlink()
    if model_kind == "directory":
        model.mkdir()
    monkeypatch.delenv("MONEYWIZ_MODEL_PATH", raising=False)
    monkeypatch.setenv("MONEYWIZ_APP", str(app))

    with pytest.raises(
        reassign_payees_by_id.ReassignmentError,
        match="MoneyWiz model file does not exist",
    ):
        reassign_payees_by_id._resolve_model()


@pytest.mark.parametrize("plist_name", ["Info.plist", "VersionInfo.plist"])
def test_resolve_model_rejects_malformed_plist(
    fake_moneywiz_app: Callable[[], tuple[Path, Path, Path]],
    monkeypatch: pytest.MonkeyPatch,
    plist_name: str,
) -> None:
    app, model_directory, _model = fake_moneywiz_app()
    plist_path = (
        app / "Contents/Info.plist"
        if plist_name == "Info.plist"
        else model_directory / plist_name
    )
    plist_path.write_bytes(b"not a plist")
    monkeypatch.delenv("MONEYWIZ_MODEL_PATH", raising=False)
    monkeypatch.setenv("MONEYWIZ_APP", str(app))

    with pytest.raises(reassign_payees_by_id.ReassignmentError, match="Cannot read"):
        reassign_payees_by_id._resolve_model()


@pytest.mark.parametrize("plist_name", ["Info.plist", "VersionInfo.plist"])
def test_resolve_model_rejects_non_dictionary_plist(
    fake_moneywiz_app: Callable[[], tuple[Path, Path, Path]],
    monkeypatch: pytest.MonkeyPatch,
    plist_name: str,
) -> None:
    app, model_directory, _model = fake_moneywiz_app()
    plist_path = (
        app / "Contents/Info.plist"
        if plist_name == "Info.plist"
        else model_directory / plist_name
    )
    with plist_path.open("wb") as plist_file:
        plistlib.dump(["not", "a", "dictionary"], plist_file)
    monkeypatch.delenv("MONEYWIZ_MODEL_PATH", raising=False)
    monkeypatch.setenv("MONEYWIZ_APP", str(app))

    with pytest.raises(
        reassign_payees_by_id.ReassignmentError, match="not a dictionary"
    ):
        reassign_payees_by_id._resolve_model()


@pytest.mark.parametrize(
    "version_info",
    [
        {},
        {"NSManagedObjectModel_CurrentVersionName": ""},
        {"NSManagedObjectModel_CurrentVersionName": 48},
        {"NSManagedObjectModel_CurrentVersionName": "  "},
    ],
)
def test_resolve_model_rejects_malformed_current_version(
    fake_moneywiz_app: Callable[[], tuple[Path, Path, Path]],
    monkeypatch: pytest.MonkeyPatch,
    version_info: dict[str, object],
) -> None:
    app, model_directory, _model = fake_moneywiz_app()
    with (model_directory / "VersionInfo.plist").open("wb") as version_file:
        plistlib.dump(version_info, version_file)
    monkeypatch.delenv("MONEYWIZ_MODEL_PATH", raising=False)
    monkeypatch.setenv("MONEYWIZ_APP", str(app))

    with pytest.raises(
        reassign_payees_by_id.ReassignmentError,
        match="invalid current version",
    ):
        reassign_payees_by_id._resolve_model()


def test_resolve_model_rejects_wrong_bundle_identifier(
    fake_moneywiz_app: Callable[[], tuple[Path, Path, Path]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _model_directory, _model = fake_moneywiz_app()
    with (app / "Contents/Info.plist").open("wb") as info_file:
        plistlib.dump({"CFBundleIdentifier": "example.invalid"}, info_file)
    monkeypatch.delenv("MONEYWIZ_MODEL_PATH", raising=False)
    monkeypatch.setenv("MONEYWIZ_APP", str(app))

    with pytest.raises(
        reassign_payees_by_id.ReassignmentError,
        match="Unexpected MoneyWiz bundle identifier",
    ):
        reassign_payees_by_id._resolve_model()


def test_resolve_model_explicit_override_bypasses_bundle_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "operator-selected-model"
    model.touch()
    monkeypatch.setenv("MONEYWIZ_MODEL_PATH", str(model))
    monkeypatch.setenv("MONEYWIZ_APP", str(tmp_path / "missing.app"))

    assert reassign_payees_by_id._resolve_model() == model


@pytest.mark.parametrize("override_kind", ["missing", "directory"])
def test_resolve_model_rejects_invalid_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, override_kind: str
) -> None:
    model = tmp_path / "operator-selected-model"
    if override_kind == "directory":
        model.mkdir()
    monkeypatch.setenv("MONEYWIZ_MODEL_PATH", str(model))

    with pytest.raises(
        reassign_payees_by_id.ReassignmentError,
        match="MONEYWIZ_MODEL_PATH does not exist",
    ):
        reassign_payees_by_id._resolve_model()


def test_moneywiz_process_check_accepts_only_stopped_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reassign_payees_by_id.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1),
    )

    reassign_payees_by_id._require_moneywiz_stopped()


@pytest.mark.parametrize("returncode", [0, 2, -9])
def test_moneywiz_process_check_rejects_running_or_abnormal_status(
    monkeypatch: pytest.MonkeyPatch, returncode: int
) -> None:
    monkeypatch.setattr(
        reassign_payees_by_id.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], returncode),
    )

    with pytest.raises(reassign_payees_by_id.ReassignmentError):
        reassign_payees_by_id._require_moneywiz_stopped()


def test_moneywiz_process_check_rejects_inspection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_inspection(*_args: object, **_kwargs: object) -> None:
        raise OSError("pgrep unavailable")

    monkeypatch.setattr(reassign_payees_by_id.subprocess, "run", fail_inspection)

    with pytest.raises(
        reassign_payees_by_id.ReassignmentError,
        match="Cannot verify whether MoneyWiz 2026 is running",
    ):
        reassign_payees_by_id._require_moneywiz_stopped()


def make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o755)
    return path


def isolate_writer_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MONEYWIZ_TOOLS_HOST", raising=False)
    monkeypatch.delenv("MONEYWIZ_CORE_DATA_WRITER", raising=False)
    monkeypatch.setattr(reassign_payees_by_id, "__file__", str(script_path))


@pytest.mark.parametrize(
    "override_variable", ["MONEYWIZ_TOOLS_HOST", "MONEYWIZ_CORE_DATA_WRITER"]
)
def test_resolve_writer_prefers_explicit_override_even_when_bundled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    override_variable: str,
) -> None:
    script = (
        tmp_path
        / "MoneyWiz Tools.app/Contents/Resources/runtime/scripts/reassign_payees_by_id.py"
    )
    bundled = make_executable(
        tmp_path / "MoneyWiz Tools.app/Contents/MacOS/MoneyWizTools"
    )
    override = make_executable(tmp_path / "operator-host")
    isolate_writer_resolution(tmp_path, monkeypatch, script)
    monkeypatch.setenv(override_variable, str(override))

    assert bundled.is_file()
    assert reassign_payees_by_id._resolve_writer() == override


def test_resolve_writer_discovers_co_bundled_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = (
        tmp_path
        / "MoneyWiz Tools.app/Contents/Resources/runtime/scripts/reassign_payees_by_id.py"
    )
    bundled = make_executable(
        tmp_path / "MoneyWiz Tools.app/Contents/MacOS/MoneyWizTools"
    )
    isolate_writer_resolution(tmp_path, monkeypatch, script)

    assert reassign_payees_by_id._resolve_writer() == bundled


def test_resolve_writer_discovers_configured_source_tree_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "checkout/scripts/reassign_payees_by_id.py"
    bundle_directory = tmp_path / "Custom Applications"
    writer = make_executable(
        bundle_directory / "MoneyWiz Tools.app/Contents/MacOS/MoneyWizTools"
    )
    isolate_writer_resolution(tmp_path, monkeypatch, script)
    install_config = tmp_path / "home/.config/moneywiz-tools/install.mk"
    install_config.parent.mkdir(parents=True)
    install_config.write_text(
        f"APP_BUNDLE_DIR := {bundle_directory}\n", encoding="utf-8"
    )

    assert reassign_payees_by_id._resolve_writer() == writer


def test_resolve_writer_uses_default_source_tree_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "checkout/scripts/reassign_payees_by_id.py"
    writer = make_executable(
        tmp_path / "home/Applications/MoneyWiz Tools.app/Contents/MacOS/MoneyWizTools"
    )
    isolate_writer_resolution(tmp_path, monkeypatch, script)

    assert reassign_payees_by_id._resolve_writer() == writer


@pytest.mark.parametrize("override_kind", ["missing", "directory", "non-executable"])
def test_resolve_writer_rejects_invalid_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, override_kind: str
) -> None:
    script = (
        tmp_path
        / "MoneyWiz Tools.app/Contents/Resources/runtime/scripts/reassign_payees_by_id.py"
    )
    make_executable(tmp_path / "MoneyWiz Tools.app/Contents/MacOS/MoneyWizTools")
    override = tmp_path / "operator-host"
    if override_kind == "directory":
        override.mkdir()
    elif override_kind == "non-executable":
        override.touch(mode=0o644)
    isolate_writer_resolution(tmp_path, monkeypatch, script)
    monkeypatch.setenv("MONEYWIZ_TOOLS_HOST", str(override))

    with pytest.raises(
        reassign_payees_by_id.ReassignmentError,
        match="override is not an executable file",
    ):
        reassign_payees_by_id._resolve_writer()


@pytest.mark.parametrize("topology", ["bundled", "source"])
def test_resolve_writer_rejects_missing_or_non_executable_installed_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, topology: str
) -> None:
    if topology == "bundled":
        script = (
            tmp_path
            / "MoneyWiz Tools.app/Contents/Resources/runtime/scripts/reassign_payees_by_id.py"
        )
        writer = tmp_path / "MoneyWiz Tools.app/Contents/MacOS/MoneyWizTools"
    else:
        script = tmp_path / "checkout/scripts/reassign_payees_by_id.py"
        writer = (
            tmp_path
            / "home/Applications/MoneyWiz Tools.app/Contents/MacOS/MoneyWizTools"
        )
    writer.parent.mkdir(parents=True)
    writer.touch(mode=0o644)
    isolate_writer_resolution(tmp_path, monkeypatch, script)

    with pytest.raises(
        reassign_payees_by_id.ReassignmentError,
        match=f"not executable.*{re.escape(str(writer))}",
    ):
        reassign_payees_by_id._resolve_writer()


@pytest.mark.parametrize(
    "config_content",
    ["", "OTHER := /tmp\n", "APP_BUNDLE_DIR := relative\n"],
)
def test_resolve_writer_rejects_invalid_install_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_content: str,
) -> None:
    script = tmp_path / "checkout/scripts/reassign_payees_by_id.py"
    isolate_writer_resolution(tmp_path, monkeypatch, script)
    install_config = tmp_path / "home/.config/moneywiz-tools/install.mk"
    install_config.parent.mkdir(parents=True)
    install_config.write_text(config_content, encoding="utf-8")

    with pytest.raises(reassign_payees_by_id.ReassignmentError):
        reassign_payees_by_id._resolve_writer()


@pytest.mark.parametrize("outcome", [0, 2, OSError("pgrep unavailable")])
def test_process_check_failure_stops_before_writer_preflight(
    monkeypatch: pytest.MonkeyPatch, outcome: int | OSError
) -> None:
    commands: list[list[str]] = []

    def inspect(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if isinstance(outcome, OSError):
            raise outcome
        return subprocess.CompletedProcess(command, outcome)

    monkeypatch.setattr(reassign_payees_by_id.subprocess, "run", inspect)
    monkeypatch.setattr(
        reassign_payees_by_id,
        "require_write_capability",
        lambda *_args, **_kwargs: pytest.fail(
            "writer compatibility preflight ran after process-check failure"
        ),
    )

    with pytest.raises(reassign_payees_by_id.ReassignmentError):
        reassign_payees_by_id.apply_coredata_payload(
            Path("unused.sqlite"),
            {"schema_version": 1, "operations": []},
            capability="write.reassign-payees-by-id",
        )

    assert commands == [["pgrep", "-x", "MoneyWiz"]]


@pytest.mark.parametrize("noop_count", [0, 1], ids=["empty-selection", "all-noop"])
@pytest.mark.parametrize("capability_state", ["verified", "blocked", "unrecognized"])
def test_empty_reassign_apply_checks_capability_without_host_preflight(
    monkeypatch: pytest.MonkeyPatch, noop_count: int, capability_state: str
) -> None:
    capability_calls: list[tuple[Path, str]] = []
    noops = (
        (
            reassign_payees_by_id.ReassignmentNoOp(
                transaction_id=1,
                transaction_gid="already-target",
                reason="already assigned to target payee",
            ),
        )
        if noop_count
        else ()
    )
    plan = reassign_payees_by_id.ReassignmentPlan(
        processed=noop_count, operations=(), noops=noops
    )

    def check_capability(db_path: Path, capability: str) -> object:
        capability_calls.append((db_path, capability))
        if capability_state != "verified":
            raise reassign_payees_by_id.CompatibilityError(capability_state)
        return object()

    monkeypatch.setattr(
        reassign_payees_by_id, "require_write_capability", check_capability
    )

    def fail_host_preflight() -> None:
        pytest.fail("host preflight ran for an empty apply plan")

    for name in ("_require_moneywiz_stopped", "_resolve_writer", "_resolve_model"):
        monkeypatch.setattr(
            reassign_payees_by_id,
            name,
            fail_host_preflight,
        )
    monkeypatch.setattr(
        reassign_payees_by_id.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail(
            "native host ran for an empty apply plan"
        ),
    )

    db_path = Path("store.sqlite")
    if capability_state == "verified":
        reassign_payees_by_id.apply_plan(db_path, plan)
    else:
        with pytest.raises(
            reassign_payees_by_id.ReassignmentError,
            match=capability_state,
        ):
            reassign_payees_by_id.apply_plan(db_path, plan)

    assert capability_calls == [(db_path, "write.reassign-payees-by-id")]


def test_nonempty_apply_preserves_process_before_capability_and_host_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[str] = []
    assessment = reassign_payees_by_id.CompatibilityAssessment(
        profile_id="verified",
        model_checksum="checksum",
        capabilities={"write.reassign-payees-by-id": "verified"},
        missing_by_profile={},
    )
    writer = tmp_path / "writer"
    model = tmp_path / "model.mom"
    writer.touch(mode=0o755)
    model.touch()

    monkeypatch.setattr(
        reassign_payees_by_id,
        "_require_moneywiz_stopped",
        lambda: events.append("process"),
    )

    def check_capability(
        _db_path: Path, _capability: str
    ) -> reassign_payees_by_id.CompatibilityAssessment:
        events.append("capability")
        return assessment

    monkeypatch.setattr(
        reassign_payees_by_id, "require_write_capability", check_capability
    )
    monkeypatch.setattr(
        reassign_payees_by_id,
        "_resolve_writer",
        lambda: events.append("writer") or writer,
    )
    monkeypatch.setattr(
        reassign_payees_by_id,
        "_resolve_model",
        lambda: events.append("model") or model,
    )

    def run_host(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        events.append("host")
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(reassign_payees_by_id.subprocess, "run", run_host)

    reassign_payees_by_id.apply_coredata_payload(
        tmp_path / "store.sqlite",
        {"schema_version": 1, "operations": [{}]},
        capability="write.reassign-payees-by-id",
    )

    assert events == ["process", "capability", "writer", "model", "host"]


def test_reassign_plan_normalizes_existing_unicode_payee(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)

    result = run_reassign(db_path, "--from-payee-id", "999", "--show-plan")

    assert result.returncode == 0, result.stderr
    assert "existing payee 200 ('Vodafone" in result.stdout
    assert "Summary: processed=3, created=1, updated=3" in result.stdout


def test_reassign_plan_reuses_one_new_payee_for_matching_descriptions(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)

    result = run_reassign(db_path, "--from-payee-id", "999", "--show-plan")

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("new payee 'New Merchant'") == 2
    assert "created=1, updated=3" in result.stdout


@pytest.mark.parametrize("insertion_order", [(301, 302), (302, 301)])
@pytest.mark.parametrize(
    ("first_description", "second_description"),
    [
        ("New Merchant", "New   Merchant"),
        ("Ｎｅｗ Merchant", "New Merchant"),
        ("NEW MERCHANT", "new merchant"),
    ],
)
def test_reassign_plan_uses_one_deterministic_name_per_new_payee_key(
    tmp_path: Path,
    insertion_order: tuple[int, int],
    first_description: str,
    second_description: str,
) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)
    withdraw_entity = 40 + TRANSACTION_TYPES.index("WithdrawTransaction")
    descriptions = {301: first_description, 302: second_description}
    gids = {301: "transaction-new-one", 302: "transaction-new-two"}
    with sqlite3.connect(db_path) as con:
        con.execute("DELETE FROM ZSYNCOBJECT WHERE Z_PK IN (301, 302)")
        for transaction_id in insertion_order:
            con.execute(
                """
                INSERT INTO ZSYNCOBJECT
                (Z_PK, Z_ENT, ZGID, ZACCOUNT2, ZDESC2, ZPAYEE2)
                VALUES (?, ?, ?, 100, ?, 999)
                """,
                (
                    transaction_id,
                    withdraw_entity,
                    gids[transaction_id],
                    descriptions[transaction_id],
                ),
            )

    plan = reassign_payees_by_id.build_plan(
        db_path,
        from_payee_id=999,
        from_empty_payee=False,
        empty_desc_target_payee_id=None,
    )
    new_payee_operations = [
        operation for operation in plan.operations if operation.new_payee_key
    ]

    assert [operation.transaction_id for operation in new_payee_operations] == [
        301,
        302,
    ]
    assert {operation.new_payee_key for operation in new_payee_operations} == {
        "1:new merchant"
    }
    assert {operation.new_payee_name for operation in new_payee_operations} == {
        first_description
    }
    assert {
        operation.writer_payload()["new_payee_name"]
        for operation in new_payee_operations
    } == {first_description}


def test_reassign_plan_isolates_canonical_new_payee_names_by_user(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)
    withdraw_entity = 40 + TRANSACTION_TYPES.index("WithdrawTransaction")
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT INTO ZUSER (Z_PK) VALUES (2)")
        con.execute("INSERT INTO ZSYNCOBJECT (Z_PK, Z_ENT, ZUSER) VALUES (101, 10, 2)")
        con.executemany(
            """
            INSERT INTO ZSYNCOBJECT
            (Z_PK, Z_ENT, ZGID, ZACCOUNT2, ZDESC2, ZPAYEE2)
            VALUES (?, ?, ?, 101, ?, 999)
            """,
            [
                (303, withdraw_entity, "transaction-user-two-one", "NEW MERCHANT"),
                (304, withdraw_entity, "transaction-user-two-two", "New   Merchant"),
            ],
        )

    plan = reassign_payees_by_id.build_plan(
        db_path,
        from_payee_id=999,
        from_empty_payee=False,
        empty_desc_target_payee_id=None,
    )
    names_by_user: dict[int, set[str | None]] = {}
    for operation in plan.operations:
        if operation.new_payee_key:
            names_by_user.setdefault(operation.user_id, set()).add(
                operation.new_payee_name
            )

    assert names_by_user == {1: {"New Merchant"}, 2: {"NEW MERCHANT"}}


def test_reassign_plan_reports_explicit_already_target_noop(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)
    with sqlite3.connect(db_path) as con:
        con.execute("UPDATE ZSYNCOBJECT SET ZPAYEE2 = 200 WHERE Z_PK = 300")

    result = run_reassign(db_path, "--from-payee-id", "200", "--show-plan")

    assert result.returncode == 0, result.stderr
    assert "tx 300 -> no-op (already assigned to target payee)" in result.stdout
    assert "Summary: processed=1, created=0, updated=0, noops=1" in result.stdout


@pytest.mark.parametrize(
    ("setup_sql", "message"),
    [
        ("UPDATE ZSYNCOBJECT SET ZACCOUNT2 = NULL WHERE Z_PK = 300", "has no account"),
        (
            "UPDATE ZSYNCOBJECT SET ZACCOUNT2 = 404 WHERE Z_PK = 300",
            "references missing or invalid account 404",
        ),
        ("UPDATE ZSYNCOBJECT SET ZUSER = NULL WHERE Z_PK = 100", "has no owner"),
        (
            "UPDATE ZSYNCOBJECT SET ZUSER = 404 WHERE Z_PK = 100",
            "references missing or invalid owner 404",
        ),
    ],
)
def test_reassign_rejects_unresolved_account_ownership(
    tmp_path: Path, setup_sql: str, message: str
) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)
    with sqlite3.connect(db_path) as con:
        con.execute(setup_sql)

    result = run_reassign(db_path, "--from-payee-id", "999")

    assert result.returncode == 2
    assert message in result.stderr
    assert "-- DRY-RUN --" not in result.stdout


def test_reassign_rejects_selected_transaction_without_gid(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)
    with sqlite3.connect(db_path) as con:
        con.execute("UPDATE ZSYNCOBJECT SET ZGID = '  ' WHERE Z_PK = 301")

    result = run_reassign(db_path, "--from-payee-id", "999")

    assert result.returncode == 2
    assert "Transaction 301 has no GID" in result.stderr
    assert "-- DRY-RUN --" not in result.stdout


def test_reassign_rejects_account_reference_to_non_account_row(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT INTO ZSYNCOBJECT (Z_PK, Z_ENT, ZUSER) VALUES (404, 29, 1)")
        con.execute("UPDATE ZSYNCOBJECT SET ZACCOUNT2 = 404 WHERE Z_PK = 300")

    result = run_reassign(db_path, "--from-payee-id", "999")

    assert result.returncode == 2
    assert "references missing or invalid account 404" in result.stderr
    assert "-- DRY-RUN --" not in result.stdout


def test_reassign_rejects_empty_description_without_fallback(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)
    with sqlite3.connect(db_path) as con:
        con.execute("UPDATE ZSYNCOBJECT SET ZDESC2 = '' WHERE Z_PK = 301")

    result = run_reassign(db_path, "--from-payee-id", "999")

    assert result.returncode == 2
    assert (
        "Transaction 301 has an empty description and no fallback payee"
        in result.stderr
    )
    assert "-- DRY-RUN --" not in result.stdout


def test_reassign_invalid_parameters_are_clean_errors(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)

    result = run_reassign(
        db_path,
        "--from-empty-payee",
        "--empty-desc-target-payee-id",
        "404",
    )

    assert result.returncode == 2
    assert "not a valid Payee id" in result.stderr
    assert "Traceback" not in result.stderr


def prepare_empty_description_fallback(
    db_path: Path, *, payee_id: int, payee_user_id: int
) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            INSERT INTO ZSYNCOBJECT (Z_PK, Z_ENT, ZGID, ZNAME5, ZUSER7)
            VALUES (?, 29, ?, 'Fallback', ?)
            """,
            (payee_id, f"payee-{payee_id}", payee_user_id),
        )
        con.execute(
            "UPDATE ZSYNCOBJECT SET ZDESC2 = '', ZPAYEE2 = NULL WHERE Z_PK = 300"
        )


def test_reassign_accepts_same_user_fallback_payee(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)
    prepare_empty_description_fallback(db_path, payee_id=201, payee_user_id=1)

    result = run_reassign(
        db_path,
        "--from-empty-payee",
        "--empty-desc-target-payee-id",
        "201",
        "--show-plan",
    )

    assert result.returncode == 0, result.stderr
    assert (
        "tx 300 (WithdrawTransaction) -> existing payee 201 ('Fallback')"
        in result.stdout
    )


def test_reassign_rejects_cross_user_fallback_payee(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)
    prepare_empty_description_fallback(db_path, payee_id=201, payee_user_id=2)

    result = run_reassign(
        db_path,
        "--from-empty-payee",
        "--empty-desc-target-payee-id",
        "201",
    )

    assert result.returncode == 2
    assert (
        "Fallback payee id 201 belongs to user 2, but transaction 300 belongs to user 1"
        in result.stderr
    )
    assert "Traceback" not in result.stderr


def test_reassign_rejects_mixed_user_fallback_plan_atomically(tmp_path: Path) -> None:
    db_path = tmp_path / "moneywiz.sqlite"
    make_database(db_path)
    prepare_empty_description_fallback(db_path, payee_id=201, payee_user_id=1)
    withdraw_entity = 40 + TRANSACTION_TYPES.index("WithdrawTransaction")
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT INTO ZUSER (Z_PK) VALUES (2)")
        con.execute("INSERT INTO ZSYNCOBJECT (Z_PK, Z_ENT, ZUSER) VALUES (101, 10, 2)")
        con.execute(
            """
            INSERT INTO ZSYNCOBJECT
            (Z_PK, Z_ENT, ZGID, ZACCOUNT2, ZDESC2, ZPAYEE2)
            VALUES (303, ?, 'transaction-user-two', 101, '', NULL)
            """,
            (withdraw_entity,),
        )

    result = run_reassign(
        db_path,
        "--from-empty-payee",
        "--empty-desc-target-payee-id",
        "201",
        "--apply",
    )

    assert result.returncode == 2
    assert "transaction 303 belongs to user 2" in result.stderr
    assert "-- APPLY --" not in result.stdout
