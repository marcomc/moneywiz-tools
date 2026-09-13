"""Resolve a fail-closed MoneyWiz app, store, model, and owner identity."""

from __future__ import annotations

import base64
import binascii
import os
import plistlib
import sqlite3
import subprocess
import unicodedata
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SETAPP_BUNDLE_IDENTIFIER = "com.moneywiz.personalfinance-setapp"
TESTFLIGHT_BUNDLE_IDENTIFIER = "com.moneywiz.personalfinance"
SUPPORTED_BUNDLE_IDENTIFIERS = frozenset(
    {SETAPP_BUNDLE_IDENTIFIER, TESTFLIGHT_BUNDLE_IDENTIFIER}
)

DEFAULT_MONEYWIZ_APP = Path("/Applications/Setapp/MoneyWiz 2026.app")
DEFAULT_TESTFLIGHT_APP = Path("/Applications/MoneyWiz.app")
LEGACY_TESTFLIGHT_APP = Path("/Applications/MoneyWiz 2026.app")

CURRENT_STORE_LEAF = Path("Data/Library/Application Support/MoneyWiz_iCloud.sqlite")
LEGACY_STORE_LEAF = Path("Data/Documents/.AppData/ipadMoneyWiz.sqlite")


class RuntimeIdentityError(Exception):
    """A user-facing runtime identity failure."""


@dataclass(frozen=True)
class AppIdentity:
    """A supported MoneyWiz application bundle."""

    path: Path
    edition: str
    bundle_identifier: str
    version: str | None
    build: str | None


@dataclass(frozen=True)
class StoreIdentity:
    """Identity fields read without mutating a MoneyWiz Core Data store."""

    path: Path
    uuid: str
    owner_local_id: int
    owner_sync_login: str | None
    model_checksum: str

    @property
    def owner_id(self) -> int:
        """Compatibility alias for the Core Data User local primary key."""
        return self.owner_local_id


@dataclass(frozen=True)
class RuntimeIdentity:
    """One unambiguous MoneyWiz application/store/model tuple."""

    app: AppIdentity
    store: StoreIdentity
    model_path: Path

    def plan_binding(self) -> dict[str, str | int | None]:
        """Return the identity fields that subsequent plans must bind."""
        return {
            "app_bundle_identifier": self.app.bundle_identifier,
            "app_edition": self.app.edition,
            "app_version": self.app.version,
            "app_build": self.app.build,
            "app_path": str(self.app.path),
            "store_path": str(self.store.path),
            "store_uuid": self.store.uuid,
            "owner_local_id": self.store.owner_local_id,
            "owner_sync_login": self.store.owner_sync_login,
            "model_path": str(self.model_path),
            "model_checksum": self.store.model_checksum,
        }


def _edition_for_identifier(bundle_identifier: str) -> str:
    if bundle_identifier == SETAPP_BUNDLE_IDENTIFIER:
        return "setapp"
    if bundle_identifier == TESTFLIGHT_BUNDLE_IDENTIFIER:
        return "testflight"
    raise RuntimeIdentityError(
        f"Unsupported MoneyWiz bundle identifier: {bundle_identifier!r}"
    )


def _load_plist(path: Path, *, description: str) -> dict[str, Any]:
    try:
        with path.open("rb") as plist_file:
            payload = plistlib.load(plist_file)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise RuntimeIdentityError(
            f"Cannot read {description} at {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeIdentityError(
            f"{description.capitalize()} is not a dictionary: {path}"
        )
    return payload


def _inspect_app(app_path: Path, *, require_release_identity: bool) -> AppIdentity:
    app = app_path.expanduser().resolve(strict=False)
    info_path = app / "Contents/Info.plist"
    app_info = _load_plist(info_path, description="MoneyWiz app metadata")
    bundle_identifier = app_info.get("CFBundleIdentifier")
    if bundle_identifier not in SUPPORTED_BUNDLE_IDENTIFIERS:
        raise RuntimeIdentityError(
            f"Unexpected MoneyWiz bundle identifier at {app}: {bundle_identifier!r}"
        )

    version = app_info.get("CFBundleShortVersionString")
    build = app_info.get("CFBundleVersion")
    if require_release_identity and (
        not isinstance(version, str)
        or not version
        or version != version.strip()
        or not isinstance(build, str)
        or not build
        or build != build.strip()
    ):
        raise RuntimeIdentityError(
            f"MoneyWiz app has incomplete version identity at {info_path}"
        )
    return AppIdentity(
        path=app,
        edition=_edition_for_identifier(bundle_identifier),
        bundle_identifier=bundle_identifier,
        version=version if isinstance(version, str) and version else None,
        build=build if isinstance(build, str) and build else None,
    )


def inspect_app(app_path: Path) -> AppIdentity:
    """Validate one explicit, fully identified MoneyWiz application bundle."""
    return _inspect_app(app_path, require_release_identity=True)


def _default_app_candidates() -> tuple[Path, ...]:
    return DEFAULT_TESTFLIGHT_APP, LEGACY_TESTFLIGHT_APP, DEFAULT_MONEYWIZ_APP


def resolve_app(
    app_path: Path | None = None,
    *,
    candidates: Sequence[Path] | None = None,
    environ: Mapping[str, str] | None = None,
) -> AppIdentity:
    """Resolve one supported app; explicit path and ``MONEYWIZ_APP`` win."""
    environment = os.environ if environ is None else environ
    configured = app_path
    if configured is None and environment.get("MONEYWIZ_APP"):
        configured = Path(environment["MONEYWIZ_APP"])
    if configured is not None:
        return inspect_app(configured)

    app_candidates = tuple(
        candidates if candidates is not None else _default_app_candidates()
    )
    valid: list[AppIdentity] = []
    failures: list[str] = []
    seen: set[Path] = set()
    for candidate in app_candidates:
        expanded = candidate.expanduser()
        canonical = expanded.resolve(strict=False)
        if canonical in seen or not expanded.exists():
            continue
        seen.add(canonical)
        try:
            valid.append(inspect_app(expanded))
        except RuntimeIdentityError as exc:
            failures.append(str(exc))

    if len(valid) > 1:
        paths = ", ".join(str(identity.path) for identity in valid)
        raise RuntimeIdentityError(
            f"Multiple supported MoneyWiz app bundles found: {paths}. Set MONEYWIZ_APP."
        )
    if valid:
        return valid[0]
    if failures:
        raise RuntimeIdentityError(
            "No valid supported MoneyWiz app bundle found; " + "; ".join(failures)
        )
    searched = ", ".join(str(path.expanduser()) for path in app_candidates)
    raise RuntimeIdentityError(
        f"No supported MoneyWiz app bundle found. Searched: {searched}"
    )


def resolve_model(
    app_path: Path | None = None,
    model_path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve an explicit model or the validated current app manifest leaf."""
    environment = os.environ if environ is None else environ
    configured_model = model_path
    if configured_model is None and environment.get("MONEYWIZ_MODEL_PATH"):
        configured_model = Path(environment["MONEYWIZ_MODEL_PATH"])
    if configured_model is not None:
        model = configured_model.expanduser().resolve(strict=False)
        if model.is_file():
            return model
        raise RuntimeIdentityError(f"MONEYWIZ_MODEL_PATH does not exist: {model}")

    configured_app = app_path
    if configured_app is None and environment.get("MONEYWIZ_APP"):
        configured_app = Path(environment["MONEYWIZ_APP"])
    if configured_app is None:
        app = resolve_app(environ=environment)
    else:
        app = _inspect_app(configured_app, require_release_identity=False)

    model_directory = app.path / "Contents/Resources/MoneyWizDataModel.momd"
    version_info_path = model_directory / "VersionInfo.plist"
    version_info = _load_plist(version_info_path, description="MoneyWiz model manifest")
    version_name = version_info.get("NSManagedObjectModel_CurrentVersionName")
    if (
        not isinstance(version_name, str)
        or not version_name
        or version_name != version_name.strip()
    ):
        raise RuntimeIdentityError(
            "MoneyWiz model manifest has an invalid current version: "
            f"{version_info_path}"
        )
    version_leaf = Path(version_name)
    if (
        version_leaf.is_absolute()
        or len(version_leaf.parts) != 1
        or version_leaf.name != version_name
        or version_name in {".", ".."}
        or any(unicodedata.category(char).startswith("C") for char in version_name)
    ):
        raise RuntimeIdentityError(
            "MoneyWiz model manifest current version must be a single file name: "
            f"{version_name!r}"
        )
    if version_name.endswith(".mom"):
        model_stem = version_name[: -len(".mom")]
        if not model_stem or model_stem in {".", ".."}:
            raise RuntimeIdentityError(
                "MoneyWiz model manifest has an invalid current version: "
                f"{version_info_path}"
            )
        model_leaf = version_name
    elif version_leaf.suffix:
        raise RuntimeIdentityError(
            "MoneyWiz model manifest current version has an unsupported suffix: "
            f"{version_name!r}"
        )
    else:
        model_leaf = f"{version_name}.mom"
    model = model_directory / model_leaf
    if not model.is_file():
        raise RuntimeIdentityError(f"MoneyWiz model file does not exist: {model}")
    return model.resolve()


def _resolve_model_checksum_host(
    host_path: Path | None, *, environ: Mapping[str, str]
) -> Path:
    configured = host_path
    if configured is None:
        configured_value = environ.get("MONEYWIZ_TOOLS_HOST") or environ.get(
            "MONEYWIZ_CORE_DATA_WRITER"
        )
        if configured_value:
            configured = Path(configured_value)
    if configured is None:
        script_path = Path(__file__).resolve()
        runtime_root = script_path.parents[1]
        if (
            runtime_root.name == "runtime"
            and runtime_root.parent.name == "Resources"
            and runtime_root.parent.parent.name == "Contents"
        ):
            configured = runtime_root.parent.parent / "MacOS/MoneyWizTools"
    if configured is None:
        raise RuntimeIdentityError(
            "MoneyWiz Tools host is required to verify the selected model checksum; "
            "set MONEYWIZ_TOOLS_HOST"
        )
    host = configured.expanduser().resolve(strict=False)
    if not host.is_file() or not os.access(host, os.X_OK):
        raise RuntimeIdentityError(
            f"MoneyWiz Tools model-checksum host is not executable: {host}"
        )
    return host


def inspect_model_checksum(
    model_path: Path,
    *,
    host_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    """Ask the native read-only host for Core Data's exact model checksum."""
    environment = os.environ if environ is None else environ
    model = model_path.expanduser().resolve(strict=False)
    if not model.is_file():
        raise RuntimeIdentityError(f"MoneyWiz model file does not exist: {model}")
    host = _resolve_model_checksum_host(host_path, environ=environment)
    try:
        completed = runner(
            [str(host), "--model-checksum", str(model)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeIdentityError(
            f"Cannot inspect MoneyWiz model checksum: {exc}"
        ) from exc
    checksum = completed.stdout.strip()
    if completed.returncode != 0:
        detail = completed.stderr.strip() or checksum or "unknown native host error"
        raise RuntimeIdentityError(f"Cannot inspect MoneyWiz model checksum: {detail}")
    if "\n" in checksum or not _is_model_checksum(checksum):
        raise RuntimeIdentityError(
            "MoneyWiz Tools host returned an invalid model checksum"
        )
    return checksum


def _is_model_checksum(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        return len(base64.b64decode(value, validate=True)) == 32
    except (binascii.Error, ValueError):
        return False


def _validate_store_uuid(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RuntimeIdentityError("Core Data metadata has no valid store UUID")
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError) as exc:
        raise RuntimeIdentityError(
            "Core Data metadata has no valid store UUID"
        ) from exc
    if str(parsed).casefold() != value.casefold():
        raise RuntimeIdentityError("Core Data metadata has no valid store UUID")
    return value


def _store_metadata(connection: sqlite3.Connection) -> tuple[str, str]:
    rows = connection.execute("SELECT Z_UUID, Z_PLIST FROM Z_METADATA").fetchall()
    if len(rows) != 1:
        raise RuntimeIdentityError(
            "Database must contain exactly one Core Data metadata record; "
            f"found {len(rows)}"
        )
    store_uuid = _validate_store_uuid(rows[0][0])
    raw_plist = rows[0][1]
    if isinstance(raw_plist, memoryview):
        raw_plist = raw_plist.tobytes()
    if not isinstance(raw_plist, bytes):
        raise RuntimeIdentityError("Core Data metadata plist is not binary data")
    try:
        metadata = plistlib.loads(raw_plist)
    except plistlib.InvalidFileException as exc:
        raise RuntimeIdentityError(
            f"Cannot parse Core Data metadata plist: {exc}"
        ) from exc
    if not isinstance(metadata, dict):
        raise RuntimeIdentityError("Core Data metadata plist is not a dictionary")
    checksum = metadata.get("NSStoreModelVersionChecksumKey")
    if not _is_model_checksum(checksum):
        raise RuntimeIdentityError("Core Data metadata has no valid model checksum")
    return store_uuid, checksum


def _resolve_owner(
    connection: sqlite3.Connection, owner_id: int | None
) -> tuple[int, str | None]:
    if isinstance(owner_id, bool) or (
        owner_id is not None and not isinstance(owner_id, int)
    ):
        raise RuntimeIdentityError("MoneyWiz owner id must be an integer")
    user_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(ZUSER)").fetchall()
    }
    if "Z_PK" not in user_columns:
        raise RuntimeIdentityError("MoneyWiz store has no User local identity column")
    sync_login_expression = "ZSYNCLOGIN" if "ZSYNCLOGIN" in user_columns else "NULL"
    rows = connection.execute(
        f"SELECT Z_PK, {sync_login_expression} FROM ZUSER "
        "WHERE Z_PK IS NOT NULL ORDER BY Z_PK"
    ).fetchall()
    owners = {int(row[0]): row[1] for row in rows}
    if owner_id is not None:
        if owner_id not in owners:
            raise RuntimeIdentityError(
                f"MoneyWiz owner {owner_id} does not exist in the selected store"
            )
        selected = owner_id
    elif len(owners) != 1:
        owner_list = ", ".join(str(value) for value in owners) or "none"
        raise RuntimeIdentityError(
            "Selected store does not have one unambiguous owner; "
            f"found: {owner_list}. Select an owner explicitly."
        )
    else:
        selected = next(iter(owners))
    sync_login = owners[selected]
    return selected, sync_login if isinstance(sync_login, str) and sync_login else None


def inspect_store(store_path: Path, *, owner_id: int | None = None) -> StoreIdentity:
    """Read and validate one store's UUID, model checksum, and owner."""
    store = store_path.expanduser().resolve(strict=False)
    if not store.is_file():
        raise RuntimeIdentityError(f"MoneyWiz store does not exist: {store}")
    uri = store.resolve().as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise RuntimeIdentityError(
            f"Cannot open MoneyWiz store read-only: {exc}"
        ) from exc
    try:
        store_uuid, model_checksum = _store_metadata(connection)
        resolved_owner, owner_sync_login = _resolve_owner(connection, owner_id)
    except sqlite3.Error as exc:
        raise RuntimeIdentityError(
            f"Cannot inspect MoneyWiz store identity: {exc}"
        ) from exc
    finally:
        connection.close()
    return StoreIdentity(
        path=store,
        uuid=store_uuid,
        owner_local_id=resolved_owner,
        owner_sync_login=owner_sync_login,
        model_checksum=model_checksum,
    )


def default_store_candidates(
    *, home: Path | None = None, bundle_identifier: str | None = None
) -> tuple[Path, ...]:
    """Return only canonical store locations for supported MoneyWiz editions."""
    home_directory = Path.home() if home is None else home.expanduser()
    identifiers = (
        (bundle_identifier,)
        if bundle_identifier is not None
        else (TESTFLIGHT_BUNDLE_IDENTIFIER, SETAPP_BUNDLE_IDENTIFIER)
    )
    unsupported = set(identifiers).difference(SUPPORTED_BUNDLE_IDENTIFIERS)
    if unsupported:
        raise RuntimeIdentityError(
            f"Unsupported MoneyWiz bundle identifier: {min(unsupported)!r}"
        )
    return tuple(
        home_directory / "Library/Containers" / identifier / leaf
        for identifier in identifiers
        for leaf in (CURRENT_STORE_LEAF, LEGACY_STORE_LEAF)
    )


def resolve_store(
    store_path: Path | None = None,
    *,
    owner_id: int | None = None,
    bundle_identifier: str | None = None,
    candidates: Sequence[Path] | None = None,
    home: Path | None = None,
) -> StoreIdentity:
    """Resolve one store without guessing outside supported canonical locations."""
    if store_path is not None:
        return inspect_store(store_path, owner_id=owner_id)

    store_candidates = tuple(
        candidates
        if candidates is not None
        else default_store_candidates(home=home, bundle_identifier=bundle_identifier)
    )
    valid: list[StoreIdentity] = []
    failures: list[str] = []
    seen: set[Path] = set()
    for candidate in store_candidates:
        expanded = candidate.expanduser()
        canonical = expanded.resolve(strict=False)
        if canonical in seen or not expanded.exists():
            continue
        seen.add(canonical)
        try:
            valid.append(inspect_store(expanded, owner_id=owner_id))
        except RuntimeIdentityError as exc:
            failures.append(f"{expanded}: {exc}")

    if len(valid) > 1:
        paths = ", ".join(str(identity.path) for identity in valid)
        raise RuntimeIdentityError(
            f"Multiple valid MoneyWiz stores found: {paths}. Select a store explicitly."
        )
    if valid:
        return valid[0]
    if failures:
        raise RuntimeIdentityError(
            "No valid MoneyWiz store found; " + "; ".join(failures)
        )
    searched = ", ".join(str(path.expanduser()) for path in store_candidates)
    raise RuntimeIdentityError(f"No MoneyWiz store found. Searched: {searched}")


def resolve_runtime_identity(
    store_path: Path | None = None,
    *,
    owner_id: int | None = None,
    app_path: Path | None = None,
    model_path: Path | None = None,
    model_checksum_host: Path | None = None,
    model_checksum_reader: Callable[[Path], str] | None = None,
    app_candidates: Sequence[Path] | None = None,
    store_candidates: Sequence[Path] | None = None,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> RuntimeIdentity:
    """Resolve one app/store/model identity with explicit choices taking priority."""
    app = resolve_app(app_path, candidates=app_candidates, environ=environ)
    store = resolve_store(
        store_path,
        owner_id=owner_id,
        bundle_identifier=app.bundle_identifier,
        candidates=store_candidates,
        home=home,
    )
    model = resolve_model(app.path, model_path, environ=environ)
    selected_model_checksum = (
        model_checksum_reader(model)
        if model_checksum_reader is not None
        else inspect_model_checksum(
            model, host_path=model_checksum_host, environ=environ
        )
    )
    if not _is_model_checksum(selected_model_checksum):
        raise RuntimeIdentityError("Selected model has an invalid checksum")
    if selected_model_checksum != store.model_checksum:
        raise RuntimeIdentityError(
            "Selected MoneyWiz model checksum does not match the store metadata: "
            f"model {selected_model_checksum}, store {store.model_checksum}"
        )
    return RuntimeIdentity(app=app, store=store, model_path=model)
