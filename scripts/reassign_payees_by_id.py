#!/usr/bin/env python3
"""Reassign transaction payees through MoneyWiz-compatible Core Data history."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import sqlite3
import subprocess
import tempfile
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from compatibility import CompatibilityError, require_write_capability

DEFAULT_MONEYWIZ_APP = Path("/Applications/Setapp/MoneyWiz 2026.app")
EXPECTED_BUNDLE_IDENTIFIER = "com.moneywiz.personalfinance-setapp"

TRANSACTION_TYPENAMES: tuple[str, ...] = (
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

PAYEE_RELEVANT_EMPTY_TYPENAMES: tuple[str, ...] = (
    "DepositTransaction",
    "RefundTransaction",
    "WithdrawTransaction",
)


class ReassignmentError(Exception):
    """A user-facing failure with no Python traceback."""


@dataclass(frozen=True)
class ExistingPayee:
    id: int
    gid: str | None
    name: str
    user_id: int


@dataclass(frozen=True)
class Reassignment:
    transaction_id: int
    transaction_gid: str
    transaction_entity: str
    user_id: int
    existing_payee: ExistingPayee | None = None
    new_payee_key: str | None = None
    new_payee_name: str | None = None

    def writer_payload(self) -> dict[str, str | None]:
        return {
            "transaction_gid": self.transaction_gid,
            "transaction_entity": self.transaction_entity,
            "existing_payee_gid": (
                self.existing_payee.gid if self.existing_payee is not None else None
            ),
            "new_payee_key": self.new_payee_key,
            "new_payee_name": self.new_payee_name,
        }


@dataclass(frozen=True)
class ReassignmentPlan:
    processed: int
    operations: tuple[Reassignment, ...]

    @property
    def created_count(self) -> int:
        return len({op.new_payee_key for op in self.operations if op.new_payee_key})

    @property
    def updated_count(self) -> int:
        return len(self.operations)


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


def normalize_payee_name(value: str) -> str:
    """Compare user-visible payee names across Unicode and whitespace variants."""
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _dict_connection(db_path: Path) -> sqlite3.Connection:
    db_uri = db_path.expanduser().resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(db_uri, uri=True)

    def dict_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            column[0]: row[index] for index, column in enumerate(cursor.description)
        }

    con.row_factory = dict_factory
    return con


def _entity_ids(con: sqlite3.Connection, typenames: Sequence[str]) -> dict[str, int]:
    placeholders = ",".join("?" * len(typenames))
    rows = con.execute(
        f"SELECT Z_ENT, Z_NAME FROM Z_PRIMARYKEY WHERE Z_NAME IN ({placeholders})",
        tuple(typenames),
    ).fetchall()
    result = {str(row["Z_NAME"]): int(row["Z_ENT"]) for row in rows}
    missing = sorted(set(typenames).difference(result))
    if missing:
        raise ReassignmentError(
            "Database does not expose required entity types: " + ", ".join(missing)
        )
    return result


def _new_payee_key(user_id: int, normalized_name: str) -> str:
    return f"{user_id}:{normalized_name}"


def _payee_for_id(
    payees_by_id: dict[int, ExistingPayee], payee_id: int
) -> ExistingPayee:
    payee = payees_by_id.get(payee_id)
    if payee is None:
        raise ReassignmentError(
            f"--empty-desc-target-payee-id {payee_id} is not a valid Payee id"
        )
    if not payee.gid:
        raise ReassignmentError(
            f"Payee id {payee_id} has no GID and cannot be used by the Core Data writer"
        )
    return payee


def _select_existing_payee(
    candidates: list[ExistingPayee], description: str, user_id: int
) -> ExistingPayee:
    if len(candidates) != 1:
        ids = ", ".join(str(payee.id) for payee in candidates)
        raise ReassignmentError(
            f"Ambiguous payee match for description {description!r}, user {user_id}: ids {ids}. "
            "Resolve duplicate payees before applying this reassignment."
        )
    payee = candidates[0]
    if not payee.gid:
        raise ReassignmentError(
            f"Payee id {payee.id} has no GID and cannot be used by the Core Data writer"
        )
    return payee


def build_plan(
    db_path: Path,
    *,
    from_payee_id: int | None,
    from_empty_payee: bool,
    empty_desc_target_payee_id: int | None,
) -> ReassignmentPlan:
    """Build a read-only plan; all actual writes occur in the Swift writer."""
    con = _dict_connection(db_path)
    try:
        typenames = (*TRANSACTION_TYPENAMES, "Payee")
        entity_ids = _entity_ids(con, typenames)
        payee_entity = entity_ids["Payee"]
        transaction_entity_by_id = {
            entity_ids[name]: name for name in TRANSACTION_TYPENAMES
        }
        empty_payee_entities = [
            entity_ids[name] for name in PAYEE_RELEVANT_EMPTY_TYPENAMES
        ]

        payees_by_id: dict[int, ExistingPayee] = {}
        payees_by_name_user: dict[tuple[str, int], list[ExistingPayee]] = {}
        for row in con.execute(
            "SELECT Z_PK, ZGID, ZNAME5, ZUSER7 FROM ZSYNCOBJECT WHERE Z_ENT = ?",
            (payee_entity,),
        ).fetchall():
            name = row.get("ZNAME5")
            user = row.get("ZUSER7")
            if name is None or user is None:
                continue
            payee = ExistingPayee(
                id=int(row["Z_PK"]),
                gid=str(row["ZGID"]) if row.get("ZGID") else None,
                name=str(name),
                user_id=int(user),
            )
            payees_by_id[payee.id] = payee
            payees_by_name_user.setdefault(
                (normalize_payee_name(payee.name), payee.user_id), []
            ).append(payee)

        fallback_payee: ExistingPayee | None = None
        if empty_desc_target_payee_id is not None:
            fallback_payee = _payee_for_id(payees_by_id, empty_desc_target_payee_id)

        transaction_entities = list(transaction_entity_by_id)
        transaction_placeholders = ",".join("?" * len(transaction_entities))
        filters: list[str] = []
        params: list[Any] = [payee_entity, *transaction_entities]
        if from_payee_id is not None:
            filters.append("t.ZPAYEE2 = ?")
            params.append(from_payee_id)
        if from_empty_payee:
            empty_placeholders = ",".join("?" * len(empty_payee_entities))
            filters.append(
                f"(t.Z_ENT IN ({empty_placeholders}) AND "
                "(t.ZPAYEE2 IS NULL OR t.ZPAYEE2 = 0 OR "
                "(t.ZPAYEE2 IS NOT NULL AND (p.ZNAME5 IS NULL OR TRIM(p.ZNAME5) = ''))))"
            )
            params.extend(empty_payee_entities)
        filter_sql = " OR ".join(filters)
        transaction_rows = con.execute(
            (
                "SELECT t.Z_PK, t.ZGID, t.Z_ENT, t.ZACCOUNT2, t.ZDESC2, t.ZPAYEE2 "
                "FROM ZSYNCOBJECT AS t "
                "LEFT JOIN ZSYNCOBJECT AS p "
                "ON p.Z_PK = t.ZPAYEE2 AND p.Z_ENT = ? "
                f"WHERE t.Z_ENT IN ({transaction_placeholders}) AND ({filter_sql})"
            ),
            params,
        ).fetchall()

        account_ids = sorted(
            {
                int(row["ZACCOUNT2"])
                for row in transaction_rows
                if row.get("ZACCOUNT2") is not None
            }
        )
        account_user_by_id: dict[int, int] = {}
        if account_ids:
            placeholders = ",".join("?" * len(account_ids))
            for row in con.execute(
                f"SELECT Z_PK, ZUSER FROM ZSYNCOBJECT WHERE Z_PK IN ({placeholders})",
                account_ids,
            ).fetchall():
                if row.get("ZUSER") is not None:
                    account_user_by_id[int(row["Z_PK"])] = int(row["ZUSER"])

        operations: list[Reassignment] = []
        for row in transaction_rows:
            transaction_id = int(row["Z_PK"])
            account_id = row.get("ZACCOUNT2")
            if account_id is None:
                continue
            user_id = account_user_by_id.get(int(account_id))
            if user_id is None:
                continue
            transaction_gid = row.get("ZGID")
            if not transaction_gid:
                raise ReassignmentError(
                    f"Transaction {transaction_id} has no GID and cannot be used by the Core Data writer"
                )

            description_raw = row.get("ZDESC2")
            description = (
                str(description_raw).strip() if description_raw is not None else ""
            )
            target_existing: ExistingPayee | None = None
            new_payee_key: str | None = None
            new_payee_name: str | None = None
            if description:
                normalized_description = normalize_payee_name(description)
                candidates = payees_by_name_user.get(
                    (normalized_description, user_id), []
                )
                if candidates:
                    target_existing = _select_existing_payee(
                        candidates, description, user_id
                    )
                else:
                    new_payee_key = _new_payee_key(user_id, normalized_description)
                    new_payee_name = description
            elif fallback_payee is not None:
                if fallback_payee.user_id != user_id:
                    raise ReassignmentError(
                        f"Fallback payee id {fallback_payee.id} belongs to user "
                        f"{fallback_payee.user_id}, but transaction {transaction_id} "
                        f"belongs to user {user_id}"
                    )
                target_existing = fallback_payee
            else:
                continue

            target_id = target_existing.id if target_existing is not None else None
            if target_id is not None and row.get("ZPAYEE2") == target_id:
                continue
            operations.append(
                Reassignment(
                    transaction_id=transaction_id,
                    transaction_gid=str(transaction_gid),
                    transaction_entity=transaction_entity_by_id[int(row["Z_ENT"])],
                    user_id=user_id,
                    existing_payee=target_existing,
                    new_payee_key=new_payee_key,
                    new_payee_name=new_payee_name,
                )
            )
        return ReassignmentPlan(
            processed=len(transaction_rows), operations=tuple(operations)
        )
    finally:
        con.close()


def _moneywiz_is_running() -> bool:
    try:
        completed = subprocess.run(
            ["pgrep", "-x", "MoneyWiz"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return completed.returncode == 0


def _resolve_writer() -> Path:
    configured = os.environ.get("MONEYWIZ_TOOLS_HOST") or os.environ.get(
        "MONEYWIZ_CORE_DATA_WRITER"
    )
    if configured:
        writer = Path(configured).expanduser()
    else:
        runtime_root = Path(__file__).resolve().parents[1]
        bundle_contents = runtime_root.parent.parent
        writer = bundle_contents / "MacOS/MoneyWizTools"
    if not writer.is_file() or not os.access(writer, os.X_OK):
        raise ReassignmentError(
            f"MoneyWiz Tools Core Data host is not installed at {writer}. Run: make install"
        )
    return writer


def _resolve_model() -> Path:
    configured = os.environ.get("MONEYWIZ_MODEL_PATH")
    if configured:
        model = Path(configured).expanduser()
        if model.is_file():
            return model
        raise ReassignmentError(f"MONEYWIZ_MODEL_PATH does not exist: {model}")

    app = Path(os.environ.get("MONEYWIZ_APP", DEFAULT_MONEYWIZ_APP)).expanduser()
    info_path = app / "Contents/Info.plist"
    try:
        with info_path.open("rb") as info_file:
            app_info = plistlib.load(info_file)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise ReassignmentError(
            f"Cannot read MoneyWiz app metadata at {info_path}: {exc}"
        ) from exc
    if app_info.get("CFBundleIdentifier") != EXPECTED_BUNDLE_IDENTIFIER:
        raise ReassignmentError(
            f"Unexpected MoneyWiz bundle identifier at {app}: {app_info.get('CFBundleIdentifier')!r}"
        )

    model_directory = app / "Contents/Resources/MoneyWizDataModel.momd"
    version_info_path = model_directory / "VersionInfo.plist"
    try:
        with version_info_path.open("rb") as version_file:
            version_info = plistlib.load(version_file)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise ReassignmentError(
            f"Cannot read MoneyWiz model manifest at {version_info_path}: {exc}"
        ) from exc
    version_name = version_info.get("NSManagedObjectModel_CurrentVersionName")
    if not isinstance(version_name, str) or not version_name:
        raise ReassignmentError(
            f"MoneyWiz model manifest has no current version: {version_info_path}"
        )
    model = model_directory / f"{version_name}.mom"
    if not model.is_file():
        raise ReassignmentError(f"MoneyWiz model file does not exist: {model}")
    return model


def apply_coredata_payload(
    db_path: Path, payload: dict[str, Any], *, capability: str
) -> None:
    if _moneywiz_is_running():
        raise ReassignmentError(
            "Quit MoneyWiz 2026 before --apply. The compatible writer needs exclusive "
            "access so MoneyWiz can consume the saved history when it is reopened."
        )

    try:
        assessment = require_write_capability(db_path, capability)
    except CompatibilityError as exc:
        raise ReassignmentError(str(exc)) from exc

    writer = _resolve_writer()
    model = _resolve_model()
    writer_payload = dict(payload)
    writer_payload["contract_version"] = 1
    writer_payload["profile_id"] = assessment.profile_id
    with tempfile.TemporaryDirectory(prefix="moneywiz-coredata-") as temp_dir:
        plan_path = Path(temp_dir) / "plan.json"
        plan_path.write_text(
            json.dumps(writer_payload, ensure_ascii=False), encoding="utf-8"
        )
        completed = subprocess.run(
            [
                str(writer),
                "--coredata-write",
                "--store",
                str(db_path.expanduser().resolve()),
                "--model",
                str(model),
                "--plan",
                str(plan_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip() or completed.stdout.strip() or "unknown failure"
        )
        raise ReassignmentError(f"Compatible Core Data writer failed: {detail}")
    if completed.stdout.strip():
        print(completed.stdout.strip())


def apply_plan(db_path: Path, plan: ReassignmentPlan) -> None:
    if not plan.operations:
        return
    apply_coredata_payload(
        db_path,
        {
            "schema_version": 1,
            "operations": [operation.writer_payload() for operation in plan.operations],
        },
        capability="write.reassign-payees-by-id",
    )


def _print_plan(plan: ReassignmentPlan) -> None:
    for index, operation in enumerate(plan.operations, start=1):
        if operation.existing_payee is not None:
            target = (
                f"existing payee {operation.existing_payee.id} "
                f"({operation.existing_payee.name!r})"
            )
        else:
            target = f"new payee {operation.new_payee_name!r}"
        print(
            f"[{index}] tx {operation.transaction_id} ({operation.transaction_entity}) "
            f"-> {target}"
        )


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reassign selected transactions to payees matching their descriptions. "
            "New payees are created through MoneyWiz-compatible Core Data history."
        )
    )
    parser.add_argument(
        "--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB"
    )
    parser.add_argument(
        "--from-payee-id", type=int, help="Payee id to replace in transactions"
    )
    parser.add_argument(
        "--from-empty-payee",
        action="store_true",
        help=(
            "Include expense/income-like transactions whose payee is NULL, zero, or blank"
        ),
    )
    parser.add_argument(
        "--empty-desc-target-payee-id",
        type=int,
        help="Assign this payee when a selected transaction has an empty description",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Apply the Core Data write"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress per-transaction plan output"
    )
    parser.add_argument(
        "--show-plan",
        action="store_true",
        help="Print the semantic Core Data plan, including with --apply",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.from_payee_id is None and not args.from_empty_payee:
        parser.error(
            "provide at least one selector: --from-payee-id ID and/or --from-empty-payee"
        )
    db_path = args.db.expanduser()
    if not db_path.is_file():
        print(f"error: database file not found: {db_path}", file=os.sys.stderr)
        return 2

    try:
        plan = build_plan(
            db_path,
            from_payee_id=args.from_payee_id,
            from_empty_payee=args.from_empty_payee,
            empty_desc_target_payee_id=args.empty_desc_target_payee_id,
        )
        print("-- " + ("APPLY" if args.apply else "DRY-RUN") + " --")
        if (not args.quiet) or args.show_plan:
            _print_plan(plan)
        if args.apply:
            apply_plan(db_path, plan)
        print(
            f"\nSummary: processed={plan.processed}, created={plan.created_count}, "
            f"updated={plan.updated_count}"
        )
        if args.apply and plan.operations:
            print("Reopen MoneyWiz and wait for iCloud Sync to report Up to Date.")
        return 0
    except (ReassignmentError, sqlite3.Error, OSError, ValueError) as exc:
        print(f"error: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
