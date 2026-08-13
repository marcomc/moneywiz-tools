import json
import plistlib
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import compatibility
import reassign_payees_by_id

FIXTURE_CHECKSUM = "KxT0qIvWI+7n1S58SHjQOJ8x50TIqI0l+sXzUGx8y18="
LIVE_CHECKSUM = "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ="
FUTURE_CHECKSUM = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


def set_store_checksum(db_path: Path, checksum: str | None) -> None:
    with sqlite3.connect(db_path) as connection:
        metadata = {}
        if checksum is not None:
            metadata["NSStoreModelVersionChecksumKey"] = checksum
        encoded = plistlib.dumps(metadata, fmt=plistlib.FMT_BINARY)
        connection.execute("UPDATE Z_METADATA SET Z_PLIST = ?", (encoded,))


def make_live_structure(db_path: Path, checksum: str = LIVE_CHECKSUM) -> None:
    shutil.copy(REPO_ROOT / "tests/test_db.sqlite", db_path)
    with sqlite3.connect(db_path) as connection:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(ZSYNCOBJECT)")
        }
        for column in [
            "ZGID",
            "ZDESC2",
            "ZPAYEE2",
            "ZNAME5",
            "ZUSER7",
            "ZNUMBEROFSHARES",
            "ZPRICEPERSHARE",
            "ZPRICEPERSHARE1",
        ]:
            if column not in columns:
                connection.execute(f"ALTER TABLE ZSYNCOBJECT ADD COLUMN {column}")
        existing_entities = {
            str(row[0]) for row in connection.execute("SELECT Z_NAME FROM Z_PRIMARYKEY")
        }
        required_entities = [
            "Payee",
            "DepositTransaction",
            "WithdrawTransaction",
            "RefundTransaction",
            "TransferDepositTransaction",
            "TransferWithdrawTransaction",
        ]
        next_id = 1000
        for entity in required_entities:
            if entity not in existing_entities:
                connection.execute(
                    "INSERT INTO Z_PRIMARYKEY (Z_ENT, Z_NAME) VALUES (?, ?)",
                    (next_id, entity),
                )
                next_id += 1
    set_store_checksum(db_path, checksum)


def test_exact_fixture_checksum_selects_fixture_profile(tmp_path: Path) -> None:
    db_path = tmp_path / "fixture.sqlite"
    shutil.copy(REPO_ROOT / "tests/test_db.sqlite", db_path)

    assessment = compatibility.assess_database(db_path)

    assert assessment.profile_id == "suffixed-investment-columns-fixture"
    assert assessment.model_checksum == FIXTURE_CHECKSUM


def test_future_structural_superset_is_not_verified_as_model_48(tmp_path: Path) -> None:
    db_path = tmp_path / "future.sqlite"
    make_live_structure(db_path, FUTURE_CHECKSUM)

    assessment = compatibility.assess_database(db_path)

    assert assessment.profile_id is None
    assert assessment.model_checksum == FUTURE_CHECKSUM
    assert any(
        missing.startswith("model-checksum:")
        for missing in assessment.missing_by_profile["moneywiz-2026-model-48"]
    )
    with pytest.raises(compatibility.CompatibilityError, match="not a recognized"):
        compatibility.require_write_capability(db_path, "write.reassign-payees-by-id")


@pytest.mark.parametrize(
    "metadata_state", ["missing", "malformed", "array", "scalar", "duplicate"]
)
def test_invalid_store_metadata_fails_closed(
    tmp_path: Path, metadata_state: str
) -> None:
    db_path = tmp_path / "invalid-metadata.sqlite"
    make_live_structure(db_path)
    with sqlite3.connect(db_path) as connection:
        if metadata_state == "missing":
            metadata = plistlib.dumps({}, fmt=plistlib.FMT_BINARY)
            connection.execute("UPDATE Z_METADATA SET Z_PLIST = ?", (metadata,))
        elif metadata_state == "malformed":
            connection.execute("UPDATE Z_METADATA SET Z_PLIST = ?", (b"not a plist",))
        elif metadata_state in {"array", "scalar"}:
            metadata = plistlib.dumps(
                [] if metadata_state == "array" else "not-a-dictionary",
                fmt=plistlib.FMT_BINARY,
            )
            connection.execute("UPDATE Z_METADATA SET Z_PLIST = ?", (metadata,))
        else:
            connection.execute(
                "INSERT INTO Z_METADATA (Z_VERSION, Z_UUID, Z_PLIST) "
                "SELECT Z_VERSION + 1, Z_UUID, Z_PLIST FROM Z_METADATA LIMIT 1"
            )

    with pytest.raises(compatibility.CompatibilityError):
        compatibility.assess_database(db_path)


@pytest.mark.parametrize("matrix_root", [[], "not-a-dictionary", None])
def test_non_dictionary_compatibility_matrix_fails_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    matrix_root: object,
) -> None:
    matrix_path = tmp_path / "compatibility-matrix.json"
    matrix_path.write_text(json.dumps(matrix_root), encoding="utf-8")
    monkeypatch.setattr(compatibility, "MATRIX_PATH", matrix_path)

    with pytest.raises(
        compatibility.CompatibilityError,
        match="matrix root is not a dictionary",
    ):
        compatibility._load_matrix()


@pytest.mark.parametrize(
    ("metadata", "expected_error"),
    [
        ([], "metadata plist is not a dictionary"),
        ("not-a-dictionary", "metadata plist is not a dictionary"),
        (
            {"NSStoreModelVersionChecksumKey": []},
            "metadata has no valid model checksum",
        ),
        (
            {"NSStoreModelVersionChecksumKey": 48},
            "metadata has no valid model checksum",
        ),
    ],
)
def test_invalid_metadata_shape_is_a_clean_cli_and_write_preflight_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    metadata: object,
    expected_error: str,
) -> None:
    db_path = tmp_path / "invalid-metadata.sqlite"
    make_live_structure(db_path)
    with sqlite3.connect(db_path) as connection:
        encoded = plistlib.dumps(metadata, fmt=plistlib.FMT_BINARY)
        connection.execute("UPDATE Z_METADATA SET Z_PLIST = ?", (encoded,))

    assert compatibility.main(["--db", str(db_path)]) == 2
    captured = capsys.readouterr()
    assert expected_error in captured.err
    assert "Traceback" not in captured.err

    monkeypatch.setattr(
        reassign_payees_by_id, "_require_moneywiz_stopped", lambda: None
    )
    monkeypatch.setattr(
        reassign_payees_by_id,
        "_resolve_writer",
        lambda: pytest.fail("writer resolved after invalid compatibility metadata"),
    )
    with pytest.raises(
        reassign_payees_by_id.ReassignmentError,
        match=expected_error,
    ):
        reassign_payees_by_id.apply_coredata_payload(
            db_path,
            {"schema_version": 1, "operations": []},
            capability="write.reassign-payees-by-id",
        )


@pytest.mark.parametrize(
    ("failure_stage", "expected_error"),
    [
        ("open", "cannot open database read-only"),
        ("query", "cannot inspect database schema"),
        ("close", "cannot close database after schema inspection"),
    ],
)
def test_sqlite_lifecycle_failures_are_clean_cli_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
    expected_error: str,
) -> None:
    db_path = tmp_path / "store.sqlite"
    db_path.touch()

    class FailingConnection:
        def close(self) -> None:
            if failure_stage == "close":
                raise sqlite3.OperationalError("injected close failure")

    if failure_stage == "open":
        monkeypatch.setattr(
            compatibility,
            "_open_read_only",
            lambda _db_path: (_ for _ in ()).throw(
                sqlite3.OperationalError("injected open failure")
            ),
        )
    else:
        monkeypatch.setattr(
            compatibility, "_open_read_only", lambda _db_path: FailingConnection()
        )
        if failure_stage == "query":
            monkeypatch.setattr(
                compatibility,
                "_schema_facts",
                lambda _connection: (_ for _ in ()).throw(
                    sqlite3.OperationalError("injected query failure")
                ),
            )
        else:
            monkeypatch.setattr(
                compatibility,
                "_schema_facts",
                lambda _connection: (set(), set(), set(), FIXTURE_CHECKSUM),
            )

    assert compatibility.main(["--db", str(db_path)]) == 2
    captured = capsys.readouterr()
    assert expected_error in captured.err
    assert "Traceback" not in captured.err


def test_unexpected_schema_failure_still_closes_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "store.sqlite"
    db_path.touch()
    closed = False

    class CloseSpy:
        def close(self) -> None:
            nonlocal closed
            closed = True

    monkeypatch.setattr(compatibility, "_open_read_only", lambda _db_path: CloseSpy())
    monkeypatch.setattr(
        compatibility,
        "_schema_facts",
        lambda _connection: (_ for _ in ()).throw(RuntimeError("unexpected failure")),
    )

    with pytest.raises(RuntimeError, match="unexpected failure"):
        compatibility.assess_database(db_path)
    assert closed


def test_primary_schema_failure_wins_when_close_also_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "store.sqlite"
    db_path.touch()

    class FailingClose:
        def close(self) -> None:
            raise sqlite3.OperationalError("injected close failure")

    monkeypatch.setattr(
        compatibility, "_open_read_only", lambda _db_path: FailingClose()
    )
    monkeypatch.setattr(
        compatibility,
        "_schema_facts",
        lambda _connection: (_ for _ in ()).throw(RuntimeError("primary failure")),
    )

    with pytest.raises(RuntimeError, match="primary failure"):
        compatibility.assess_database(db_path)


@pytest.mark.parametrize(
    ("capability", "expected_status", "expected_state"),
    [
        (None, 0, None),
        ("write.reassign-payees-by-id", 0, "verified"),
        ("write.unknown", 1, "blocked"),
    ],
)
def test_json_and_table_share_capability_outcome(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    capability: str | None,
    expected_status: int,
    expected_state: str | None,
) -> None:
    db_path = tmp_path / "live.sqlite"
    make_live_structure(db_path)
    extra_args = ["--capability", capability] if capability else []

    table_status = compatibility.main(["--db", str(db_path), *extra_args])
    capsys.readouterr()
    json_status = compatibility.main(
        ["--db", str(db_path), *extra_args, "--format", "json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert table_status == json_status == expected_status
    assert payload["requested_capability_state"] == expected_state


def test_json_and_table_both_reject_unrecognized_profile(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "future.sqlite"
    make_live_structure(db_path, FUTURE_CHECKSUM)

    table_status = compatibility.main(["--db", str(db_path)])
    capsys.readouterr()
    json_status = compatibility.main(["--db", str(db_path), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert table_status == json_status == 1
    assert payload["profile_id"] is None


def test_writer_payload_binds_verified_model_checksum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_payload: dict[str, object] = {}
    assessment = compatibility.CompatibilityAssessment(
        profile_id="moneywiz-2026-model-48",
        model_checksum=LIVE_CHECKSUM,
        capabilities={"write.reassign-payees-by-id": "verified"},
        missing_by_profile={},
    )
    writer = tmp_path / "writer"
    model = tmp_path / "model.mom"
    writer.touch(mode=0o755)
    model.touch()

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        plan_path = Path(command[command.index("--plan") + 1])
        plan_payload.update(json.loads(plan_path.read_text(encoding="utf-8")))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        reassign_payees_by_id, "_require_moneywiz_stopped", lambda: None
    )
    monkeypatch.setattr(
        reassign_payees_by_id,
        "require_write_capability",
        lambda _db_path, _capability: assessment,
    )
    monkeypatch.setattr(reassign_payees_by_id, "_resolve_writer", lambda: writer)
    monkeypatch.setattr(reassign_payees_by_id, "_resolve_model", lambda: model)
    monkeypatch.setattr(reassign_payees_by_id.subprocess, "run", fake_run)

    reassign_payees_by_id.apply_coredata_payload(
        tmp_path / "store.sqlite",
        {"schema_version": 1, "operations": []},
        capability="write.reassign-payees-by-id",
    )

    assert plan_payload["profile_id"] == "moneywiz-2026-model-48"
    assert plan_payload["model_checksum"] == LIVE_CHECKSUM
    assert plan_payload["capability"] == "write.reassign-payees-by-id"
