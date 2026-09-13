"""Private durable journals and consistent SQLite snapshots for P1F writes."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from write_plan import PlanValidationError, validate_plan, validate_result


class JournalError(RuntimeError):
    """Raised when durable recovery evidence cannot be safely maintained."""


def _secure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir() or path.is_symlink() or path.stat().st_uid != os.getuid():
        raise JournalError(f"journal path is not a safe directory: {path}")
    path.chmod(0o700)
    return path.resolve()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_json(path: Path) -> dict[str, Any]:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise JournalError("journal data must be an owned regular file")
        with os.fdopen(descriptor, "r", encoding="utf-8") as source:
            descriptor = -1
            value = json.load(source)
        if not isinstance(value, dict):
            raise JournalError("journal data must be an object")
        return value
    except (OSError, ValueError) as exc:
        raise JournalError(f"cannot read journal data: {path.name}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=".journal-", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(
                payload,
                output,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise JournalError(f"cannot persist journal record: {path.name}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _create_json(path: Path, payload: dict[str, Any]) -> None:
    """Create initial evidence without an overwrite window."""
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(
                payload,
                output,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except OSError as exc:
        raise JournalError(f"cannot create journal record: {exc}") from exc


@dataclass(frozen=True)
class JournalPaths:
    root: Path
    reports: Path | None
    journal_provenance: str = "platform-default"
    report_provenance: str = "unconfigured"

    def locations(self) -> dict[str, str | None]:
        """Report configured paths without creating or chmodding anything."""
        root = self.root.expanduser()
        journal_source = self.journal_provenance
        report_source = self.report_provenance
        return {
            "journal_root": str(root),
            "entries": str(root / "entries"),
            "backups": str(root / "backups"),
            "reports": str(self.reports) if self.reports else None,
            "config_provenance": f"journal={journal_source};report={report_source}",
            "retention": {
                "verified_days": 90,
                "unresolved": "indefinite",
                "snapshots": "indefinite",
                "reports": "indefinite",
            },
            "writer_locks": str(default_data_root() / "locks"),
        }

    @classmethod
    def from_environ(cls, environ: dict[str, str] | None = None) -> JournalPaths:
        environment = os.environ if environ is None else environ
        configured = environment.get("MONEYWIZ_JOURNAL_DIR")
        journal_provenance = (
            "MONEYWIZ_JOURNAL_DIR" if configured else "platform-default"
        )
        if configured:
            root = Path(configured).expanduser()
        elif sys.platform == "darwin":
            root = Path.home() / "Library/Application Support/MoneyWiz Tools"
        else:
            root = (
                Path(
                    environment.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))
                )
                / "moneywiz-tools"
            )
        report_value = environment.get("MONEYWIZ_REPORT_DIR")
        report_provenance = "MONEYWIZ_REPORT_DIR" if report_value else "unconfigured"
        config_path = root / "config.json"
        if not report_value and config_path.is_file() and not config_path.is_symlink():
            try:
                config = _read_json(config_path)
                configured_report = config.get("obsidian_report_dir")
                if isinstance(configured_report, str) and configured_report.strip():
                    report_value = configured_report
                    report_provenance = "config.json:obsidian_report_dir"
            except (OSError, JournalError) as exc:
                raise JournalError("cannot read private report configuration") from exc
        reports = Path(report_value).expanduser() if report_value else None
        if not root.is_absolute() or (
            reports is not None and not reports.is_absolute()
        ):
            raise JournalError("journal and report paths must be absolute")
        return cls(
            root=root,
            reports=reports,
            journal_provenance=journal_provenance,
            report_provenance=report_provenance,
        )


class JournalStore:
    """Own journal state; verified entries expire after 90 days, unresolved do not."""

    def __init__(self, paths: JournalPaths, *, create: bool = True) -> None:
        if not create:
            self.paths = paths
            self.entries = paths.root / "entries"
            self.backups = paths.root / "backups"
            return
        self.paths = JournalPaths(
            root=_secure_directory(paths.root),
            reports=paths.reports,
            journal_provenance=paths.journal_provenance,
            report_provenance=paths.report_provenance,
        )
        self.entries = _secure_directory(self.paths.root / "entries")
        self.backups = _secure_directory(self.paths.root / "backups")

    def locations(self) -> dict[str, str]:
        return self.paths.locations()

    def _entry_files(self) -> list[Path]:
        if self.entries.is_symlink():
            raise JournalError("journal entries directory is a symbolic link")
        return sorted(self.entries.glob("*.json"))

    def list_entries(self) -> list[dict[str, Any]]:
        """Return bounded machine-readable recovery summaries without private plan data."""
        entries: list[dict[str, Any]] = []
        for entry in self._entry_files():
            try:
                record = self.load(entry.stem)
            except JournalError:
                entries.append(
                    {"plan_id": entry.stem, "state": "unknown", "path": str(entry)}
                )
                continue
            entries.append(
                {
                    "plan_id": record.get("plan", {}).get("plan_id"),
                    "state": record.get("state"),
                    "prepared_at": record.get("prepared_at"),
                    "completed_at": record.get("completed_at"),
                    "path": str(entry),
                }
            )
        return entries

    def writer_lock(self):
        """Serialize this journal and its cleanup without waiting on a busy writer."""
        return _WriterLock(self.paths.root / "writer.lock")

    def _entry_path(self, plan_id: str) -> Path:
        if (
            not isinstance(plan_id, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", plan_id)
            or ".." in plan_id
        ):
            raise JournalError("unsafe plan_id")
        return self.entries / f"{plan_id}.json"

    def prepare(self, plan: dict[str, Any], store_path: Path) -> dict[str, Any]:
        entry_path = self._entry_path(plan["plan_id"])
        if entry_path.exists():
            raise JournalError(
                "journal record already exists; recover before any retry"
            )
        self._reserve_source_event(plan)
        backup = self.backups / f"{plan['plan_id']}.sqlite"
        created_backup = False
        try:
            descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
            created_backup = True
            source = sqlite3.connect(
                f"file:{quote(str(store_path.resolve()))}?mode=ro", uri=True, timeout=0
            )
            destination = sqlite3.connect(backup, timeout=0)
            try:
                deadline = time.monotonic() + 5

                def progress(_: int, __: int, ___: int) -> None:
                    if time.monotonic() >= deadline:
                        raise JournalError(
                            "consistent SQLite backup remained busy for 5 seconds"
                        )

                source.backup(destination, pages=32, sleep=0.05, progress=progress)
                destination.commit()
            finally:
                destination.close()
                source.close()
            backup.chmod(0o600)
            descriptor = os.open(backup, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            parent = os.open(self.backups, os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        except (OSError, sqlite3.Error, JournalError) as exc:
            if created_backup:
                backup.unlink(missing_ok=True)
            raise JournalError(f"cannot make consistent SQLite backup: {exc}") from exc
        record = {
            "version": 1,
            "state": "prepared",
            "prepared_at": datetime.now(UTC).isoformat(),
            "plan": plan,
            "store_path": str(store_path.resolve()),
            "backup": str(backup),
            "result": None,
            "references": [],
            "ever_verified": False,
        }
        _create_json(entry_path, record)
        return record

    def _reserve_source_event(self, plan: dict[str, Any]) -> None:
        """Reject source-event reuse even when a caller changes the plan ID."""
        key = (
            plan.get("store_identity", {}).get("store_uuid"),
            plan.get("owner_uri"),
            plan.get("source_event_id"),
        )
        reservations = _secure_directory(self.paths.root / "reservations")
        digest = hashlib.sha256(
            json.dumps(key, separators=(",", ":")).encode()
        ).hexdigest()
        reservation = reservations / f"{digest}.json"
        if reservation.exists() or reservation.is_symlink():
            existing = _read_json(reservation)
            if existing.get("plan_digest") != plan.get("plan_digest") or existing.get(
                "plan_id"
            ) != plan.get("plan_id"):
                raise JournalError(
                    "source_event_id is already reserved by a different reviewed plan"
                )
        else:
            _create_json(
                reservation,
                {"plan_id": plan["plan_id"], "plan_digest": plan["plan_digest"]},
            )

    def load(self, plan_id: str) -> dict[str, Any]:
        record = _read_json(self._entry_path(plan_id))
        if (
            record.get("version") != 1
            or not isinstance(record.get("plan"), dict)
            or record["plan"].get("plan_id") != plan_id
        ):
            raise JournalError("journal identity or version is malformed")
        return record

    def record_result(
        self,
        plan_id: str,
        result: dict[str, Any],
        *,
        preserve_completed_at: bool = False,
    ) -> dict[str, Any]:
        record = self.load(plan_id)
        classification = result.get("classification")
        record["state"] = (
            "verified"
            if classification in {"applied", "noop"} and result.get("verified") is True
            else "unresolved"
        )
        record["ever_verified"] = (
            record.get("ever_verified") is True or record["state"] == "verified"
        )
        record["result"] = result
        if not preserve_completed_at or not record.get("completed_at"):
            record["completed_at"] = datetime.now(UTC).isoformat()
        _write_json(self._entry_path(plan_id), record)
        return record

    def cleanup(self, *, apply: bool, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(UTC)
        candidates = self._eligible(current)
        preview = [self._preview(plan_id) for plan_id in candidates]
        deleted: list[str] = []
        if apply and candidates:
            # Same lock order as execution. Never wait for an active writer.
            stores = sorted(
                {self.load(plan_id)["store_path"] for plan_id in candidates}
            )
            with ExitStack() as stack:
                for store in stores:
                    stack.enter_context(store_lock(Path(store)))
                stack.enter_context(self.writer_lock())
                eligible = set(self._eligible(now or datetime.now(UTC)))
                selected = [plan_id for plan_id in candidates if plan_id in eligible]
                receipt = {
                    "version": 1,
                    "cleaned_at": current.isoformat(),
                    "status": "prepared",
                    "eligible_plan_ids": selected,
                    "deleted_plan_ids": [],
                    "snapshot_policy": "retained-indefinitely-p1f",
                }
                receipt_path = self.paths.root / "cleanup-receipt.json"
                _write_json(receipt_path, receipt)
                for plan_id in selected:
                    self._entry_path(plan_id).unlink()
                    deleted.append(plan_id)
                _fsync_directory(self.entries)
                _write_json(
                    receipt_path,
                    {**receipt, "status": "complete", "deleted_plan_ids": deleted},
                )
        return {
            "eligible": preview,
            "estimated_reclaimable_bytes": sum(
                item["estimated_reclaimable_bytes"] for item in preview
            ),
            "deleted": deleted,
            "dry_run": not apply,
            "snapshot_policy": "retained-indefinitely-p1f",
        }

    def _preview(self, plan_id: str) -> dict[str, Any]:
        entry = self._entry_path(plan_id)
        return {
            "plan_id": plan_id,
            "reason": "verified result older than 90 days with no references; snapshot retained",
            "estimated_reclaimable_bytes": entry.stat().st_size,
        }

    def _eligible(self, current: datetime) -> list[str]:
        records = {}
        protected: set[str] = set()
        for entry in self._entry_files():
            try:
                record = self.load(entry.stem)
                references = record.get("references")
                if not isinstance(references, list) or any(
                    not isinstance(reference, str) for reference in references
                ):
                    return []  # Unknown reference graph: retain all potentially referenced evidence.
                protected.update(references)
                records[entry.stem] = record
            except JournalError:
                return []
        candidates: list[str] = []
        for plan_id, record in records.items():
            result = record.get("result")
            if (
                plan_id in protected
                or record.get("state") != "verified"
                or not isinstance(result, dict)
                or result.get("verified") is not True
                or result.get("classification") not in {"applied", "noop"}
            ):
                continue
            if (
                not isinstance(record.get("store_path"), str)
                or not Path(record["store_path"]).is_file()
            ):
                continue
            try:
                validated_plan = validate_plan(record["plan"])
                validate_result(validated_plan, result)
            except (PlanValidationError, TypeError, ValueError, KeyError):
                continue
            try:
                completed = datetime.fromisoformat(record["completed_at"])
            except (KeyError, TypeError, ValueError):
                continue
            if (
                completed.tzinfo is not None
                and completed + timedelta(days=90) <= current
            ):
                candidates.append(plan_id)
        return candidates


def default_data_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/MoneyWiz Tools"
    return (
        Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        / "moneywiz-tools"
    )


class _WriterLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.descriptor = -1

    def __enter__(self) -> int:
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise JournalError("writer lock must be an owned regular file")
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.descriptor = descriptor
            return descriptor
        except OSError as exc:
            os.close(descriptor)
            raise JournalError(
                "another cooperating writer or cleanup holds the lock"
            ) from exc
        except BaseException:
            os.close(descriptor)
            raise

    def __exit__(self, *_: object) -> None:
        if self.descriptor >= 0:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            os.close(self.descriptor)
            self.descriptor = -1


@contextmanager
def store_lock(store: Path):
    metadata = store.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise JournalError("store must be a regular file")
    root = _secure_directory(default_data_root())
    locks = _secure_directory(root / "locks")
    with _WriterLock(locks / f"{metadata.st_dev}-{metadata.st_ino}.lock") as descriptor:
        yield descriptor
