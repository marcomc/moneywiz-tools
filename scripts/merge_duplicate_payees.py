#!/usr/bin/env python3
"""Plan exact payee consolidation and export fuzzy pairs for manual approval."""

from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from reassign_payees_by_id import (
    ReassignmentError,
    _dict_connection,
    _entity_ids,
    apply_coredata_payload,
    normalize_payee_name,
    require_coredata_write_capability,
)

SIMILARITY_THRESHOLD = 0.88


@dataclass(frozen=True)
class Payee:
    """A live Payee with the reference counts used for canonical selection."""

    id: int
    gid: str | None
    name: str
    user_id: int
    zpayee2_references: int
    string_history_references: int

    @property
    def reference_count(self) -> int:
        return self.zpayee2_references + self.string_history_references


@dataclass(frozen=True)
class ExactDuplicateGroup:
    """One per-user exact-normalized group with a deterministic survivor."""

    user_id: int
    normalized_name: str
    canonical: Payee
    duplicates: tuple[Payee, ...]
    blocked_reason: str | None


@dataclass(frozen=True)
class FuzzyCandidate:
    """A similar but non-exact pair that cannot be applied automatically."""

    user_id: int
    left: Payee
    right: Payee
    similarity: float
    reason: str


@dataclass(frozen=True)
class DuplicatePayeePlan:
    """The read-only plan passed to output or the Core Data host."""

    payees_analyzed: int
    exact_groups: tuple[ExactDuplicateGroup, ...]
    fuzzy_candidates: tuple[FuzzyCandidate, ...] | None

    @property
    def merge_count(self) -> int:
        return sum(len(group.duplicates) for group in self.exact_groups)

    @property
    def blocked_groups(self) -> tuple[ExactDuplicateGroup, ...]:
        return tuple(group for group in self.exact_groups if group.blocked_reason)


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


def _table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _reference_counts(
    con: sqlite3.Connection,
    *,
    table_name: str,
    column_name: str,
) -> dict[int, int]:
    if not _table_exists(con, table_name):
        return {}
    rows = con.execute(
        f"SELECT {column_name} AS payee_id, COUNT(*) AS reference_count "
        f"FROM {table_name} "
        f"WHERE {column_name} IS NOT NULL AND {column_name} != 0 "
        f"GROUP BY {column_name}"
    ).fetchall()
    return {
        int(row["payee_id"]): int(row["reference_count"])
        for row in rows
        if row.get("payee_id") is not None
    }


def _load_payees(con: sqlite3.Connection) -> tuple[Payee, ...]:
    payee_entity = _entity_ids(con, ("Payee",))["Payee"]
    zpayee2_counts = _reference_counts(
        con, table_name="ZSYNCOBJECT", column_name="ZPAYEE2"
    )
    string_history_counts = _reference_counts(
        con, table_name="ZSTRINGHISTORYITEM", column_name="ZPAYEE"
    )
    payees: list[Payee] = []
    for row in con.execute(
        "SELECT Z_PK, ZGID, ZNAME5, ZUSER7 FROM ZSYNCOBJECT WHERE Z_ENT = ?",
        (payee_entity,),
    ).fetchall():
        name = row.get("ZNAME5")
        user_id = row.get("ZUSER7")
        if name is None or user_id is None:
            continue
        payee_id = int(row["Z_PK"])
        payees.append(
            Payee(
                id=payee_id,
                gid=str(row["ZGID"]) if row.get("ZGID") else None,
                name=str(name),
                user_id=int(user_id),
                zpayee2_references=zpayee2_counts.get(payee_id, 0),
                string_history_references=string_history_counts.get(payee_id, 0),
            )
        )
    return tuple(sorted(payees, key=lambda payee: (payee.user_id, payee.id)))


def _is_all_caps(value: str) -> bool:
    return any(character.isalpha() for character in value) and value.isupper()


def _uses_ascii_spaces(value: str) -> bool:
    return all(not character.isspace() or character == " " for character in value)


def canonical_sort_key(payee: Payee) -> tuple[bool, bool, int, int]:
    """Prefer readable spelling, then minimize the number of moved references."""
    return (
        _is_all_caps(payee.name),
        not _uses_ascii_spaces(payee.name),
        -payee.reference_count,
        payee.id,
    )


def loose_normalize_payee_name(value: str) -> str:
    """Normalize enough to identify review-only punctuation and accent variants."""
    decomposed = unicodedata.normalize("NFKD", normalize_payee_name(value))
    return "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character) and character.isalnum()
    )


def _is_simple_numeric_suffix_variant(left: str, right: str) -> bool:
    if len(left) == len(right):
        return False
    longer, shorter = (left, right) if len(left) > len(right) else (right, left)
    return longer.startswith(shorter) and longer[len(shorter) :].isdigit()


def _build_fuzzy_candidates(payees: Sequence[Payee]) -> tuple[FuzzyCandidate, ...]:
    candidates: list[FuzzyCandidate] = []
    by_user: dict[int, list[Payee]] = {}
    for payee in payees:
        by_user.setdefault(payee.user_id, []).append(payee)

    for user_id, user_payees in by_user.items():
        for left_index, left in enumerate(user_payees):
            left_exact = normalize_payee_name(left.name)
            left_loose = loose_normalize_payee_name(left.name)
            if not left_loose:
                continue
            for right in user_payees[left_index + 1 :]:
                right_exact = normalize_payee_name(right.name)
                if left_exact == right_exact:
                    continue
                if _is_simple_numeric_suffix_variant(left_exact, right_exact):
                    continue
                right_loose = loose_normalize_payee_name(right.name)
                if not right_loose:
                    continue
                if left_loose == right_loose:
                    candidates.append(
                        FuzzyCandidate(
                            user_id=user_id,
                            left=left,
                            right=right,
                            similarity=1.0,
                            reason="loose-normalized-equal",
                        )
                    )
                    continue

                similarity = SequenceMatcher(None, left_loose, right_loose).ratio()
                if similarity >= SIMILARITY_THRESHOLD:
                    candidates.append(
                        FuzzyCandidate(
                            user_id=user_id,
                            left=left,
                            right=right,
                            similarity=similarity,
                            reason=f"similarity>={SIMILARITY_THRESHOLD:.2f}",
                        )
                    )
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                candidate.user_id,
                -candidate.similarity,
                candidate.left.id,
                candidate.right.id,
            ),
        )
    )


def build_plan(
    db_path: Path, *, include_fuzzy_candidates: bool = False
) -> DuplicatePayeePlan:
    """Inspect a store without modifying it."""
    con = _dict_connection(db_path)
    try:
        payees = _load_payees(con)
        by_exact_name: dict[tuple[int, str], list[Payee]] = {}
        for payee in payees:
            by_exact_name.setdefault(
                (payee.user_id, normalize_payee_name(payee.name)), []
            ).append(payee)

        exact_groups: list[ExactDuplicateGroup] = []
        for (user_id, normalized_name), candidates in sorted(by_exact_name.items()):
            if len(candidates) < 2:
                continue
            ordered = tuple(sorted(candidates, key=canonical_sort_key))
            canonical = ordered[0]
            duplicates = ordered[1:]
            without_gid = [payee.id for payee in ordered if not payee.gid]
            blocked_reason = (
                "missing GID for payee ids "
                + ", ".join(str(payee_id) for payee_id in without_gid)
                if without_gid
                else None
            )
            exact_groups.append(
                ExactDuplicateGroup(
                    user_id=user_id,
                    normalized_name=normalized_name,
                    canonical=canonical,
                    duplicates=duplicates,
                    blocked_reason=blocked_reason,
                )
            )
        return DuplicatePayeePlan(
            payees_analyzed=len(payees),
            exact_groups=tuple(exact_groups),
            fuzzy_candidates=(
                _build_fuzzy_candidates(payees) if include_fuzzy_candidates else None
            ),
        )
    finally:
        con.close()


def write_fuzzy_map(
    path: Path,
    candidates: Sequence[FuzzyCandidate],
    *,
    overwrite: bool,
) -> Path:
    """Write an editable approval map; it is never used by the apply path."""
    destination = path.expanduser()
    _require_writable_fuzzy_map_destination(destination, overwrite=overwrite)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as map_file:
        writer = csv.DictWriter(
            map_file,
            fieldnames=(
                "user_id",
                "similarity",
                "reason",
                "left_id",
                "left_name",
                "right_id",
                "right_name",
                "review_decision",
                "approved_canonical_id",
                "review_notes",
            ),
        )
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(
                {
                    "user_id": candidate.user_id,
                    "similarity": f"{candidate.similarity:.3f}",
                    "reason": candidate.reason,
                    "left_id": candidate.left.id,
                    "left_name": _spreadsheet_literal(candidate.left.name),
                    "right_id": candidate.right.id,
                    "right_name": _spreadsheet_literal(candidate.right.name),
                    "review_decision": "pending",
                    "approved_canonical_id": "",
                    "review_notes": "",
                }
            )
    return destination


def _require_writable_fuzzy_map_destination(path: Path, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise ReassignmentError(
            f"fuzzy map already exists: {path}; use --overwrite-fuzzy-map to replace it"
        )


def _is_spreadsheet_formula(value: str) -> bool:
    """Classify formula-capable CSV text without changing its rendered value."""
    normalized = unicodedata.normalize("NFKC", value)
    for character in normalized:
        if character.isspace() or unicodedata.category(character).startswith("C"):
            continue
        return character in ("=", "+", "-", "@")
    return False


def _spreadsheet_literal(value: str) -> str:
    """Prevent payee names from being interpreted as spreadsheet formulas."""
    return f"'{value}" if _is_spreadsheet_formula(value) else value


def apply_exact_groups(db_path: Path, plan: DuplicatePayeePlan) -> None:
    """Submit only exact-normalized groups to the Core Data host."""
    if plan.blocked_groups:
        details = "; ".join(
            f"{group.normalized_name!r}: {group.blocked_reason}"
            for group in plan.blocked_groups
        )
        raise ReassignmentError(
            "refusing exact duplicate merge because one or more groups cannot be "
            f"addressed by Core Data: {details}"
        )

    payee_merges = [
        {
            "source_payee_gid": duplicate.gid,
            "target_payee_gid": group.canonical.gid,
        }
        for group in plan.exact_groups
        for duplicate in group.duplicates
    ]
    if not payee_merges:
        require_coredata_write_capability(db_path, "write.merge-duplicate-payees")
        return
    apply_coredata_payload(
        db_path,
        {
            "schema_version": 2,
            "operations": [],
            "payee_merges": payee_merges,
        },
        capability="write.merge-duplicate-payees",
    )


def _reference_summary(payee: Payee) -> str:
    return (
        f"ZPAYEE2={payee.zpayee2_references}, "
        f"StringHistoryItem={payee.string_history_references}"
    )


def _print_plan(plan: DuplicatePayeePlan) -> None:
    for index, group in enumerate(plan.exact_groups, start=1):
        print(
            f"[{index}] user {group.user_id}, normalized {group.normalized_name!r}: "
            f"keep {group.canonical.id} ({group.canonical.name!r}; "
            f"{_reference_summary(group.canonical)})"
        )
        for duplicate in group.duplicates:
            print(
                f"    merge {duplicate.id} ({duplicate.name!r}; "
                f"{_reference_summary(duplicate)})"
            )
        if group.blocked_reason:
            print(f"    BLOCKED: {group.blocked_reason}")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Merge exact-normalized payee duplicates through the MoneyWiz Core Data "
            "writer. Fuzzy analysis runs only when --fuzzy-map requests a manual "
            "review export."
        )
    )
    parser.add_argument(
        "--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply exact-normalized groups through the Core Data writer",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress per-group plan output"
    )
    parser.add_argument(
        "--show-plan",
        action="store_true",
        help="Print the exact-group plan, including with --apply",
    )
    parser.add_argument(
        "--fuzzy-map",
        type=Path,
        help=(
            "Analyze similar-but-nonexact pairs and write an editable "
            "pending-review CSV"
        ),
    )
    parser.add_argument(
        "--overwrite-fuzzy-map",
        action="store_true",
        help="Allow --fuzzy-map to replace an existing CSV",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.overwrite_fuzzy_map and args.fuzzy_map is None:
        parser.error("--overwrite-fuzzy-map requires --fuzzy-map PATH")

    db_path = args.db.expanduser()
    if not db_path.is_file():
        print(f"error: database file not found: {db_path}", file=os.sys.stderr)
        return 2

    try:
        if args.fuzzy_map is not None:
            _require_writable_fuzzy_map_destination(
                args.fuzzy_map.expanduser(), overwrite=args.overwrite_fuzzy_map
            )
        plan = build_plan(db_path, include_fuzzy_candidates=args.fuzzy_map is not None)
        print("-- " + ("APPLY" if args.apply else "DRY-RUN") + " --")
        if (not args.quiet) or args.show_plan:
            _print_plan(plan)
        if args.fuzzy_map is not None:
            assert plan.fuzzy_candidates is not None
            destination = write_fuzzy_map(
                args.fuzzy_map,
                plan.fuzzy_candidates,
                overwrite=args.overwrite_fuzzy_map,
            )
            print(
                f"Fuzzy review map: {destination} "
                f"({len(plan.fuzzy_candidates)} pending candidates)"
            )
        if args.apply:
            apply_exact_groups(db_path, plan)
        fuzzy_summary = (
            "not-requested"
            if plan.fuzzy_candidates is None
            else str(len(plan.fuzzy_candidates))
        )
        print(
            f"\nSummary: payees={plan.payees_analyzed}, "
            f"exact_groups={len(plan.exact_groups)}, merges={plan.merge_count}, "
            f"blocked_groups={len(plan.blocked_groups)}, "
            f"fuzzy_candidates={fuzzy_summary}"
        )
        if args.apply and plan.merge_count:
            print("Reopen MoneyWiz and wait for iCloud Sync to report Up to Date.")
        return 0
    except (ReassignmentError, sqlite3.Error, OSError, ValueError) as exc:
        print(f"error: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
