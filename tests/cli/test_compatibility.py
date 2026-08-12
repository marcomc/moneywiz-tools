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


@pytest.mark.parametrize("metadata_state", ["missing", "malformed", "duplicate"])
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
        else:
            connection.execute(
                "INSERT INTO Z_METADATA (Z_VERSION, Z_UUID, Z_PLIST) "
                "SELECT Z_VERSION + 1, Z_UUID, Z_PLIST FROM Z_METADATA LIMIT 1"
            )

    with pytest.raises(compatibility.CompatibilityError):
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

    monkeypatch.setattr(reassign_payees_by_id, "_moneywiz_is_running", lambda: False)
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
