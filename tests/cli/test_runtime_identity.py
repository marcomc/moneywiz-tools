import plistlib
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import runtime_identity

MODEL_CHECKSUM = "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ="
STORE_UUID = "D26F993E-2055-4EC9-8BB0-411FCC203048"


@pytest.fixture
def make_app(tmp_path: Path) -> Callable[[str, str], tuple[Path, Path]]:
    def create(
        bundle_identifier: str = runtime_identity.TESTFLIGHT_BUNDLE_IDENTIFIER,
        name: str = "MoneyWiz 2026.app",
    ) -> tuple[Path, Path]:
        app = tmp_path / name
        contents = app / "Contents"
        model_directory = contents / "Resources/MoneyWizDataModel.momd"
        model_directory.mkdir(parents=True)
        with (contents / "Info.plist").open("wb") as info_file:
            plistlib.dump(
                {
                    "CFBundleIdentifier": bundle_identifier,
                    "CFBundleShortVersionString": "2026.1",
                    "CFBundleVersion": "4801",
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
        return app, model

    return create


def make_store(
    path: Path,
    *,
    owner_ids: tuple[int, ...] = (1,),
    store_uuid: str = STORE_UUID,
    checksum: str = MODEL_CHECKSUM,
    with_sync_login: bool = True,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE Z_METADATA "
            "(Z_VERSION INTEGER PRIMARY KEY, Z_UUID TEXT, Z_PLIST BLOB)"
        )
        user_columns = "Z_PK INTEGER PRIMARY KEY"
        if with_sync_login:
            user_columns += ", ZSYNCLOGIN TEXT"
        connection.execute(f"CREATE TABLE ZUSER ({user_columns})")
        metadata = plistlib.dumps(
            {"NSStoreModelVersionChecksumKey": checksum}, fmt=plistlib.FMT_BINARY
        )
        connection.execute(
            "INSERT INTO Z_METADATA (Z_VERSION, Z_UUID, Z_PLIST) VALUES (1, ?, ?)",
            (store_uuid, metadata),
        )
        for owner_id in owner_ids:
            if with_sync_login:
                connection.execute(
                    "INSERT INTO ZUSER (Z_PK, ZSYNCLOGIN) VALUES (?, ?)",
                    (owner_id, f"owner-{owner_id}"),
                )
            else:
                connection.execute("INSERT INTO ZUSER (Z_PK) VALUES (?)", (owner_id,))
    return path


@pytest.mark.parametrize(
    ("bundle_identifier", "edition"),
    [
        (runtime_identity.TESTFLIGHT_BUNDLE_IDENTIFIER, "testflight"),
        (runtime_identity.SETAPP_BUNDLE_IDENTIFIER, "setapp"),
    ],
)
def test_supported_apps_resolve_their_manifest_selected_model(
    make_app: Callable[[str, str], tuple[Path, Path]],
    bundle_identifier: str,
    edition: str,
) -> None:
    app, model = make_app(bundle_identifier, f"{edition}.app")

    identity = runtime_identity.inspect_app(app)

    assert identity.edition == edition
    assert identity.bundle_identifier == bundle_identifier
    assert identity.version == "2026.1"
    assert identity.build == "4801"
    assert runtime_identity.resolve_model(app) == model


def test_explicit_model_override_retains_v1_precedence(tmp_path: Path) -> None:
    model = tmp_path / "operator-selected.mom"
    model.touch()

    assert (
        runtime_identity.resolve_model(tmp_path / "missing.app", model_path=model)
        == model
    )


def test_model_default_discovers_testflight_instead_of_defaulting_to_setapp(
    tmp_path: Path,
    make_app: Callable[[str, str], tuple[Path, Path]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, model = make_app()
    monkeypatch.setattr(runtime_identity, "DEFAULT_TESTFLIGHT_APP", app)
    monkeypatch.setattr(
        runtime_identity, "LEGACY_TESTFLIGHT_APP", tmp_path / "missing-testflight.app"
    )
    monkeypatch.setattr(
        runtime_identity, "DEFAULT_MONEYWIZ_APP", tmp_path / "missing-setapp.app"
    )

    assert runtime_identity.resolve_model(environ={}) == model


def test_full_app_identity_requires_version_and_build(
    make_app: Callable[[str, str], tuple[Path, Path]],
) -> None:
    app, model = make_app()
    with (app / "Contents/Info.plist").open("wb") as info_file:
        plistlib.dump(
            {"CFBundleIdentifier": runtime_identity.TESTFLIGHT_BUNDLE_IDENTIFIER},
            info_file,
        )

    with pytest.raises(
        runtime_identity.RuntimeIdentityError, match="incomplete version identity"
    ):
        runtime_identity.resolve_app(app, environ={})
    assert runtime_identity.resolve_model(app, environ={}) == model


def test_app_discovery_rejects_parallel_supported_editions(
    make_app: Callable[[str, str], tuple[Path, Path]],
) -> None:
    testflight, _model = make_app(
        runtime_identity.TESTFLIGHT_BUNDLE_IDENTIFIER, "testflight.app"
    )
    setapp, _model = make_app(runtime_identity.SETAPP_BUNDLE_IDENTIFIER, "setapp.app")

    with pytest.raises(
        runtime_identity.RuntimeIdentityError, match="Multiple supported"
    ):
        runtime_identity.resolve_app(candidates=(testflight, setapp), environ={})

    assert (
        runtime_identity.resolve_app(
            setapp, candidates=(testflight,), environ={}
        ).edition
        == "setapp"
    )


def test_app_discovery_rejects_an_unsupported_bundle(
    make_app: Callable[[str, str], tuple[Path, Path]],
) -> None:
    app, _model = make_app("example.invalid", "invalid.app")

    with pytest.raises(
        runtime_identity.RuntimeIdentityError,
        match="No valid supported MoneyWiz app bundle",
    ):
        runtime_identity.resolve_app(candidates=(app,), environ={})


def test_store_identity_reads_exact_metadata_and_local_owner(tmp_path: Path) -> None:
    store = make_store(tmp_path / "store.sqlite")

    identity = runtime_identity.inspect_store(store)

    assert identity.path == store
    assert identity.uuid == STORE_UUID
    assert identity.model_checksum == MODEL_CHECKSUM
    assert identity.owner_local_id == 1
    assert identity.owner_id == 1
    assert identity.owner_sync_login == "owner-1"


def test_store_identity_accepts_schema_without_optional_sync_login(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path / "store.sqlite", with_sync_login=False)

    identity = runtime_identity.inspect_store(store)

    assert identity.owner_local_id == 1
    assert identity.owner_sync_login is None


def test_store_identity_uses_read_only_sqlite_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path / "store.sqlite")
    original_connect = sqlite3.connect
    calls: list[tuple[str, bool]] = []

    def capture_connect(database: str, *, uri: bool) -> sqlite3.Connection:
        calls.append((database, uri))
        return original_connect(database, uri=uri)

    monkeypatch.setattr(runtime_identity.sqlite3, "connect", capture_connect)

    runtime_identity.inspect_store(store)

    assert calls == [(store.resolve().as_uri() + "?mode=ro", True)]


def test_multiple_store_owners_require_an_explicit_match(tmp_path: Path) -> None:
    store = make_store(tmp_path / "store.sqlite", owner_ids=(1, 2))

    with pytest.raises(
        runtime_identity.RuntimeIdentityError, match="unambiguous owner"
    ):
        runtime_identity.inspect_store(store)

    assert runtime_identity.inspect_store(store, owner_id=2).owner_local_id == 2
    with pytest.raises(runtime_identity.RuntimeIdentityError, match="does not exist"):
        runtime_identity.inspect_store(store, owner_id=3)


@pytest.mark.parametrize(
    ("store_uuid", "checksum", "message"),
    [
        ("not-a-uuid", MODEL_CHECKSUM, "valid store UUID"),
        (STORE_UUID, "not-a-checksum", "valid model checksum"),
    ],
)
def test_invalid_store_metadata_fails_closed(
    tmp_path: Path, store_uuid: str, checksum: str, message: str
) -> None:
    store = make_store(
        tmp_path / "store.sqlite", store_uuid=store_uuid, checksum=checksum
    )

    with pytest.raises(runtime_identity.RuntimeIdentityError, match=message):
        runtime_identity.inspect_store(store)


def test_store_discovery_rejects_multiple_valid_candidates(tmp_path: Path) -> None:
    current = make_store(tmp_path / "current.sqlite")
    legacy = make_store(
        tmp_path / "legacy.sqlite",
        store_uuid="4A1A2D66-BD6C-4CC6-811F-9B6920BCB04A",
    )

    with pytest.raises(
        runtime_identity.RuntimeIdentityError, match="Multiple valid MoneyWiz stores"
    ):
        runtime_identity.resolve_store(candidates=(current, legacy))

    assert runtime_identity.resolve_store(current, candidates=(legacy,)).path == current


def test_default_discovery_does_not_guess_an_arbitrary_store(tmp_path: Path) -> None:
    arbitrary_store = make_store(tmp_path / "somewhere/store.sqlite")

    with pytest.raises(
        runtime_identity.RuntimeIdentityError, match="No MoneyWiz store"
    ):
        runtime_identity.resolve_store(home=tmp_path)

    assert runtime_identity.resolve_store(arbitrary_store).path == arbitrary_store


def test_runtime_identity_binds_app_store_model_and_owner(
    tmp_path: Path,
    make_app: Callable[[str, str], tuple[Path, Path]],
) -> None:
    app, model = make_app(
        runtime_identity.TESTFLIGHT_BUNDLE_IDENTIFIER, "testflight.app"
    )
    store = make_store(tmp_path / "testflight.sqlite", owner_ids=(1, 2))

    identity = runtime_identity.resolve_runtime_identity(
        store,
        owner_id=2,
        app_path=app,
        environ={},
        model_checksum_reader=lambda _model: MODEL_CHECKSUM,
    )

    assert identity.model_path == model
    assert identity.plan_binding() == {
        "app_bundle_identifier": runtime_identity.TESTFLIGHT_BUNDLE_IDENTIFIER,
        "app_edition": "testflight",
        "app_version": "2026.1",
        "app_build": "4801",
        "app_path": str(app),
        "store_path": str(store),
        "store_uuid": STORE_UUID,
        "owner_local_id": 2,
        "owner_sync_login": "owner-2",
        "model_path": str(model),
        "model_checksum": MODEL_CHECKSUM,
    }


def test_runtime_identity_rejects_model_store_checksum_drift(
    tmp_path: Path,
    make_app: Callable[[str, str], tuple[Path, Path]],
) -> None:
    app, _model = make_app()
    store = make_store(tmp_path / "store.sqlite")
    different_checksum = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="

    with pytest.raises(
        runtime_identity.RuntimeIdentityError, match="does not match the store"
    ):
        runtime_identity.resolve_runtime_identity(
            store,
            app_path=app,
            environ={},
            model_checksum_reader=lambda _model: different_checksum,
        )


def test_native_model_checksum_inspection_uses_explicit_host(
    tmp_path: Path,
) -> None:
    model = tmp_path / "model.mom"
    model.touch()
    calls: list[list[str]] = []

    def run(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout=f"{MODEL_CHECKSUM}\n")

    checksum = runtime_identity.inspect_model_checksum(
        model,
        host_path=Path(sys.executable),
        environ={},
        runner=run,
    )

    assert checksum == MODEL_CHECKSUM
    assert calls == [
        [str(Path(sys.executable).resolve()), "--model-checksum", str(model.resolve())]
    ]


def test_default_store_candidates_are_edition_scoped(tmp_path: Path) -> None:
    candidates = runtime_identity.default_store_candidates(
        home=tmp_path,
        bundle_identifier=runtime_identity.TESTFLIGHT_BUNDLE_IDENTIFIER,
    )

    assert candidates == (
        tmp_path
        / "Library/Containers/com.moneywiz.personalfinance/Data/Library"
        / "Application Support"
        / "MoneyWiz_iCloud.sqlite",
        tmp_path
        / "Library/Containers/com.moneywiz.personalfinance/Data/Documents/.AppData"
        / "ipadMoneyWiz.sqlite",
    )


def test_default_app_candidates_include_current_testflight_bundle() -> None:
    assert runtime_identity.DEFAULT_TESTFLIGHT_APP == Path("/Applications/MoneyWiz.app")
