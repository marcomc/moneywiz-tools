#!/usr/bin/env python3
"""Detect MoneyWiz schema profiles and gate live writer capabilities."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import plistlib
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MATRIX_PATH = Path(__file__).with_name("compatibility_matrix.json")


class CompatibilityError(Exception):
    """A user-facing capability failure."""


@dataclass(frozen=True)
class CompatibilityAssessment:
    """The profile selected from a read-only store fingerprint."""

    profile_id: str | None
    model_checksum: str | None
    capabilities: dict[str, str]
    missing_by_profile: dict[str, tuple[str, ...]]


def _load_matrix() -> dict[str, Any]:
    try:
        payload = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompatibilityError(f"cannot read compatibility matrix: {exc}") from exc
    if payload.get("format_version") != 1 or not isinstance(
        payload.get("profiles"), list
    ):
        raise CompatibilityError("unsupported compatibility matrix format")
    profile_ids: set[str] = set()
    model_checksums: set[str] = set()
    for profile in payload["profiles"]:
        if not isinstance(profile, dict):
            raise CompatibilityError("compatibility matrix contains an invalid profile")
        profile_id = profile.get("id")
        if not isinstance(profile_id, str) or not profile_id:
            raise CompatibilityError(
                "compatibility matrix contains a profile without an id"
            )
        if profile_id in profile_ids:
            raise CompatibilityError(
                f"compatibility matrix contains duplicate profile id {profile_id!r}"
            )
        profile_ids.add(profile_id)

        fingerprint = profile.get("fingerprint")
        if not isinstance(fingerprint, dict):
            raise CompatibilityError(
                f"compatibility profile {profile_id!r} has no fingerprint"
            )
        checksum = fingerprint.get("exact_model_checksum")
        if not _is_model_checksum(checksum):
            raise CompatibilityError(
                f"compatibility profile {profile_id!r} has an invalid exact model checksum"
            )
        if checksum in model_checksums:
            raise CompatibilityError(
                f"compatibility matrix contains duplicate exact model checksum {checksum!r}"
            )
        model_checksums.add(checksum)
    return payload


def _is_model_checksum(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        return len(base64.b64decode(value, validate=True)) == 32
    except (binascii.Error, ValueError):
        return False


def _open_read_only(db_path: Path) -> sqlite3.Connection:
    uri = db_path.expanduser().resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _store_model_checksum(connection: sqlite3.Connection) -> str:
    rows = connection.execute("SELECT Z_PLIST FROM Z_METADATA").fetchall()
    if len(rows) != 1:
        raise CompatibilityError(
            f"database must contain exactly one Core Data metadata record; found {len(rows)}"
        )
    raw_plist = rows[0][0]
    if isinstance(raw_plist, memoryview):
        raw_plist = raw_plist.tobytes()
    if not isinstance(raw_plist, bytes):
        raise CompatibilityError("Core Data metadata plist is not binary data")
    try:
        metadata = plistlib.loads(raw_plist)
    except plistlib.InvalidFileException as exc:
        raise CompatibilityError(
            f"cannot parse Core Data metadata plist: {exc}"
        ) from exc
    checksum = metadata.get("NSStoreModelVersionChecksumKey")
    if not _is_model_checksum(checksum):
        raise CompatibilityError("Core Data metadata has no valid model checksum")
    return checksum


def _schema_facts(
    connection: sqlite3.Connection,
) -> tuple[set[str], set[str], set[str], str]:
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(ZSYNCOBJECT)").fetchall()
    }
    entities = {
        str(row[0])
        for row in connection.execute("SELECT Z_NAME FROM Z_PRIMARYKEY").fetchall()
        if row[0] is not None
    }
    return tables, columns, entities, _store_model_checksum(connection)


def _missing_requirements(
    profile: dict[str, Any],
    *,
    tables: set[str],
    columns: set[str],
    entities: set[str],
    model_checksum: str,
) -> tuple[str, ...]:
    fingerprint = profile.get("fingerprint", {})
    requirements = (
        ("table", set(fingerprint.get("required_tables", [])), tables),
        ("column", set(fingerprint.get("required_columns", [])), columns),
        ("entity", set(fingerprint.get("required_entity_names", [])), entities),
    )
    missing = [
        f"{kind}:{name}"
        for kind, expected, observed in requirements
        for name in sorted(expected.difference(observed))
    ]
    expected_checksum = fingerprint["exact_model_checksum"]
    if model_checksum != expected_checksum:
        missing.append(f"model-checksum:{expected_checksum}")
    return tuple(missing)


def assess_database(db_path: Path) -> CompatibilityAssessment:
    """Select one exact structural and Core Data model match from the registry."""
    if not db_path.expanduser().is_file():
        raise CompatibilityError(f"database file not found: {db_path}")
    matrix = _load_matrix()
    connection = _open_read_only(db_path)
    try:
        tables, columns, entities, model_checksum = _schema_facts(connection)
    except CompatibilityError:
        raise
    except sqlite3.Error as exc:
        raise CompatibilityError(f"cannot inspect database schema: {exc}") from exc
    finally:
        connection.close()

    missing_by_profile: dict[str, tuple[str, ...]] = {}
    matched_profiles: list[dict[str, Any]] = []
    for profile in matrix["profiles"]:
        profile_id = profile["id"]
        missing = _missing_requirements(
            profile,
            tables=tables,
            columns=columns,
            entities=entities,
            model_checksum=model_checksum,
        )
        missing_by_profile[profile_id] = missing
        if not missing:
            matched_profiles.append(profile)
    if len(matched_profiles) > 1:
        raise CompatibilityError("database matches more than one compatibility profile")
    if matched_profiles:
        matched = matched_profiles[0]
        capabilities = matched.get("capabilities", {})
        if not isinstance(capabilities, dict):
            raise CompatibilityError(
                f"compatibility profile {matched['id']!r} has invalid capabilities"
            )
        return CompatibilityAssessment(
            profile_id=matched["id"],
            model_checksum=model_checksum,
            capabilities={
                str(name): str(state) for name, state in capabilities.items()
            },
            missing_by_profile=missing_by_profile,
        )
    return CompatibilityAssessment(
        profile_id=None,
        model_checksum=model_checksum,
        capabilities={},
        missing_by_profile=missing_by_profile,
    )


def require_write_capability(db_path: Path, capability: str) -> CompatibilityAssessment:
    """Refuse a live write unless its profile-operation pair is verified."""
    assessment = assess_database(db_path)
    if assessment.profile_id is None:
        known_profiles = ", ".join(sorted(assessment.missing_by_profile))
        raise CompatibilityError(
            "database schema is not a recognized write profile; "
            f"known profiles: {known_profiles}. Run: moneywiz compatibility"
        )
    state = assessment.capabilities.get(capability, "blocked")
    if state != "verified":
        raise CompatibilityError(
            f"{capability} is {state} for profile {assessment.profile_id}; "
            "a verified Core Data capability is required before --apply"
        )
    return assessment


def _json_payload(
    assessment: CompatibilityAssessment, capability: str | None
) -> dict[str, Any]:
    state = _requested_capability_state(assessment, capability)
    return {
        "profile_id": assessment.profile_id,
        "model_checksum": assessment.model_checksum,
        "capabilities": assessment.capabilities,
        "requested_capability": capability,
        "requested_capability_state": state,
        "missing_by_profile": {
            profile: list(missing)
            for profile, missing in assessment.missing_by_profile.items()
        },
    }


def _requested_capability_state(
    assessment: CompatibilityAssessment, capability: str | None
) -> str | None:
    if capability is None or assessment.profile_id is None:
        return None
    return assessment.capabilities.get(capability, "blocked")


def _outcome_status(assessment: CompatibilityAssessment, capability: str | None) -> int:
    if assessment.profile_id is None:
        return 1
    if capability is None:
        return 0
    state = _requested_capability_state(assessment, capability)
    return 0 if state in {"supported", "verified"} else 1


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Show the detected schema profile and writer capability states."
    )
    parser.add_argument(
        "--db", required=True, type=Path, help="Path to MoneyWiz SQLite DB"
    )
    parser.add_argument("--capability", help="Show one capability state")
    parser.add_argument(
        "--format", choices=("table", "json"), default="table", help="Output format"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        assessment = assess_database(args.db)
        if args.format == "json":
            print(
                json.dumps(
                    _json_payload(assessment, args.capability), indent=2, sort_keys=True
                )
            )
            return _outcome_status(assessment, args.capability)
        if assessment.profile_id is None:
            print("Profile: unrecognized")
            for profile, missing in sorted(assessment.missing_by_profile.items()):
                detail = ", ".join(missing) if missing else "no matching capability"
                print(f"  {profile}: missing {detail}")
            return 1
        print(f"Profile: {assessment.profile_id}")
        if args.capability:
            state = _requested_capability_state(assessment, args.capability)
            print(f"{args.capability}: {state}")
            return _outcome_status(assessment, args.capability)
        for capability, state in sorted(assessment.capabilities.items()):
            print(f"{capability}: {state}")
        return 0
    except CompatibilityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
