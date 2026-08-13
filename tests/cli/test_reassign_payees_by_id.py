import plistlib
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
