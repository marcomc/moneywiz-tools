"""W01 fixture admission must never promote the live capability register."""

import plistlib
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import compatibility


@pytest.fixture
def disposable_store(synthetic_store: Path) -> Path:
    with sqlite3.connect(synthetic_store) as connection:
        for column in ("ZNAME5", "ZUSER7", "ZPRICEPERSHARE1"):
            connection.execute(f"ALTER TABLE ZSYNCOBJECT ADD COLUMN {column}")
        for index, entity in enumerate(
            (
                "Payee",
                "WithdrawTransaction",
                "RefundTransaction",
                "TransferDepositTransaction",
                "TransferWithdrawTransaction",
            ),
            start=100,
        ):
            connection.execute(
                "INSERT INTO Z_PRIMARYKEY VALUES (?, ?, 0)", (index, entity)
            )
        connection.execute("CREATE TABLE Z_METADATA (Z_PLIST BLOB)")
        connection.execute(
            "INSERT INTO Z_METADATA VALUES (?)",
            (
                plistlib.dumps(
                    {
                        "NSStoreModelVersionChecksumKey": "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ=",
                        compatibility.DISPOSABLE_METADATA_KEY: compatibility.DISPOSABLE_METADATA_VALUE,
                    }
                ),
            ),
        )
    return synthetic_store


@pytest.mark.parametrize(
    "capability", sorted(compatibility.DISPOSABLE_CREATE_CAPABILITIES)
)
def test_fixture_admission_does_not_grant_live_clearance(
    disposable_store: Path, capability: str
) -> None:
    assert (
        compatibility.require_disposable_write_capability(
            disposable_store, capability
        ).profile_id
        == "moneywiz-2026-model-48"
    )
    with pytest.raises(compatibility.CompatibilityError, match="blocked"):
        compatibility.require_write_capability(disposable_store, capability)


@pytest.mark.parametrize("marker", [None, "", "W01-v2", True, {"scope": "W01-v1"}])
def test_fixture_marker_is_exact(disposable_store: Path, marker: object) -> None:
    with sqlite3.connect(disposable_store) as connection:
        metadata = plistlib.loads(
            connection.execute("SELECT Z_PLIST FROM Z_METADATA").fetchone()[0]
        )
        metadata.pop(compatibility.DISPOSABLE_METADATA_KEY)
        if marker is not None:
            metadata[compatibility.DISPOSABLE_METADATA_KEY] = marker
        connection.execute(
            "UPDATE Z_METADATA SET Z_PLIST=?", (plistlib.dumps(metadata),)
        )
    with pytest.raises(
        compatibility.CompatibilityError, match="live creation remains blocked"
    ):
        compatibility.require_disposable_write_capability(
            disposable_store, "write.create-income"
        )


@pytest.mark.parametrize(
    "capability",
    [
        "write.edit-transaction",
        "write.reconcile",
        "write.unknown",
        "write.reassign-payees-by-id",
    ],
)
def test_fixture_gate_does_not_admit_other_operations(
    disposable_store: Path, capability: str
) -> None:
    with pytest.raises(compatibility.CompatibilityError, match="disposable profile"):
        compatibility.require_disposable_write_capability(disposable_store, capability)
