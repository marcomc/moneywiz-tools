#!/usr/bin/env python3
"""Detect MoneyWiz schema profiles and gate live writer capabilities."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


MATRIX_PATH = Path(__file__).with_name("compatibility_matrix.json")


class CompatibilityError(Exception):
    """A user-facing capability failure."""


@dataclass(frozen=True)
class CompatibilityAssessment:
    """The profile selected from a read-only store fingerprint."""

    profile_id: str | None
    capabilities: dict[str, str]
    missing_by_profile: dict[str, tuple[str, ...]]


def _load_matrix() -> dict[str, Any]:
    try:
        payload = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompatibilityError(f"cannot read compatibility matrix: {exc}") from exc
    if payload.get("format_version") != 1 or not isinstance(payload.get("profiles"), list):
        raise CompatibilityError("unsupported compatibility matrix format")
    return payload


def _open_read_only(db_path: Path) -> sqlite3.Connection:
    uri = db_path.expanduser().resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _schema_facts(connection: sqlite3.Connection) -> tuple[set[str], set[str], set[str]]:
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
    return tables, columns, entities


def _missing_requirements(
    profile: dict[str, Any],
    *,
    tables: set[str],
    columns: set[str],
    entities: set[str],
) -> tuple[str, ...]:
    fingerprint = profile.get("fingerprint", {})
    requirements = (
        ("table", set(fingerprint.get("required_tables", [])), tables),
        ("column", set(fingerprint.get("required_columns", [])), columns),
        ("entity", set(fingerprint.get("required_entity_names", [])), entities),
    )
    return tuple(
        f"{kind}:{name}"
        for kind, expected, observed in requirements
        for name in sorted(expected.difference(observed))
    )


def assess_database(db_path: Path) -> CompatibilityAssessment:
    """Select the first exact structural match from the packaged registry."""
    if not db_path.expanduser().is_file():
        raise CompatibilityError(f"database file not found: {db_path}")
    matrix = _load_matrix()
    connection = _open_read_only(db_path)
    try:
        tables, columns, entities = _schema_facts(connection)
    except sqlite3.Error as exc:
        raise CompatibilityError(f"cannot inspect database schema: {exc}") from exc
    finally:
        connection.close()

    missing_by_profile: dict[str, tuple[str, ...]] = {}
    for profile in matrix["profiles"]:
        profile_id = profile.get("id")
        if not isinstance(profile_id, str) or not profile_id:
            raise CompatibilityError("compatibility matrix contains a profile without an id")
        missing = _missing_requirements(
            profile, tables=tables, columns=columns, entities=entities
        )
        missing_by_profile[profile_id] = missing
        if not missing:
            capabilities = profile.get("capabilities", {})
            if not isinstance(capabilities, dict):
                raise CompatibilityError(
                    f"compatibility profile {profile_id!r} has invalid capabilities"
                )
            return CompatibilityAssessment(
                profile_id=profile_id,
                capabilities={str(name): str(state) for name, state in capabilities.items()},
                missing_by_profile=missing_by_profile,
            )
    return CompatibilityAssessment(
        profile_id=None,
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


def _json_payload(assessment: CompatibilityAssessment, capability: str | None) -> dict[str, Any]:
    state = assessment.capabilities.get(capability) if capability else None
    return {
        "profile_id": assessment.profile_id,
        "capabilities": assessment.capabilities,
        "requested_capability": capability,
        "requested_capability_state": state,
        "missing_by_profile": {
            profile: list(missing)
            for profile, missing in assessment.missing_by_profile.items()
        },
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Show the detected schema profile and writer capability states."
    )
    parser.add_argument("--db", required=True, type=Path, help="Path to MoneyWiz SQLite DB")
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
            print(json.dumps(_json_payload(assessment, args.capability), indent=2, sort_keys=True))
            return 0
        if assessment.profile_id is None:
            print("Profile: unrecognized")
            for profile, missing in sorted(assessment.missing_by_profile.items()):
                detail = ", ".join(missing) if missing else "no matching capability"
                print(f"  {profile}: missing {detail}")
            return 1
        print(f"Profile: {assessment.profile_id}")
        if args.capability:
            state = assessment.capabilities.get(args.capability, "blocked")
            print(f"{args.capability}: {state}")
            return 0 if state in {"supported", "verified"} else 1
        for capability, state in sorted(assessment.capabilities.items()):
            print(f"{capability}: {state}")
        return 0
    except CompatibilityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
