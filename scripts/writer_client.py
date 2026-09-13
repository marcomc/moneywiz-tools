"""Safe client for the version-2 native Core Data writer bridge."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from write_journal import JournalError, JournalStore, store_lock
from write_plan import PlanValidationError, validate_plan, validate_result


class WriterClientError(RuntimeError):
    """Raised for failed or untrustworthy native writer outcomes."""


def require_moneywiz_stopped(
    *, run: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run
) -> None:
    """Fail closed unless the MoneyWiz process check proves the app is closed."""
    try:
        completed = run(
            ["pgrep", "-x", "MoneyWiz"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError as exc:
        raise WriterClientError(
            f"Cannot verify whether MoneyWiz 2026 is running: {exc}"
        ) from exc
    if completed.returncode == 0:
        raise WriterClientError(
            "Quit MoneyWiz 2026 before --apply and keep it closed until the write finishes."
        )
    if completed.returncode != 1:
        raise WriterClientError(
            f"Cannot verify whether MoneyWiz 2026 is running: pgrep exited with status {completed.returncode}"
        )


def _configured_bundle_directory() -> Path:
    install_config = Path.home() / ".config/moneywiz-tools/install.mk"
    if not install_config.exists():
        return Path.home() / "Applications"
    try:
        lines = install_config.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise WriterClientError(
            f"Cannot read MoneyWiz Tools install configuration at {install_config}: {exc}"
        ) from exc
    configured_values: list[str] = []
    for line in lines:
        content = line.strip()
        if not content or content.startswith("#"):
            continue
        for operator in (":=", "?=", "="):
            prefix = f"APP_BUNDLE_DIR {operator}"
            if content.startswith(prefix):
                configured_values.append(content[len(prefix) :].strip())
                break
    if len(configured_values) != 1 or not configured_values[0]:
        raise WriterClientError(
            "MoneyWiz Tools install configuration must contain exactly one APP_BUNDLE_DIR assignment: "
            + str(install_config)
        )
    configured = Path(configured_values[0]).expanduser()
    if not configured.is_absolute():
        raise WriterClientError(
            f"APP_BUNDLE_DIR must be an absolute path in {install_config}"
        )
    return configured


def resolve_writer(*, script_file: str, environ: dict[str, str] | None = None) -> Path:
    """Resolve the bundled host without embedding a source-checkout path."""
    environment = os.environ if environ is None else environ
    configured = environment.get("MONEYWIZ_TOOLS_HOST") or environment.get(
        "MONEYWIZ_CORE_DATA_WRITER"
    )
    if configured:
        writer = Path(configured).expanduser()
        if writer.is_file() and os.access(writer, os.X_OK):
            return writer
        raise WriterClientError(
            f"MoneyWiz Tools Core Data host override is not an executable file: {writer}"
        )
    script_path = Path(script_file).resolve()
    runtime_root = script_path.parents[1]
    if (
        runtime_root.name == "runtime"
        and runtime_root.parent.name == "Resources"
        and runtime_root.parent.parent.name == "Contents"
    ):
        writer = runtime_root.parent.parent / "MacOS/MoneyWizTools"
        if writer.is_file() and os.access(writer, os.X_OK):
            return writer
        raise WriterClientError(
            f"Bundled MoneyWiz Tools Core Data host is not executable. Searched host path: {writer}. Run: make install"
        )
    bundle_root = _configured_bundle_directory()
    writer = bundle_root / "MoneyWiz Tools.app/Contents/MacOS/MoneyWizTools"
    if writer.is_file() and os.access(writer, os.X_OK):
        return writer
    raise WriterClientError(
        f"MoneyWiz Tools Core Data host is not executable. Searched installed host path: {writer}. Run: make install"
    )


def invoke_v1(
    *,
    db_path: Path,
    payload: dict[str, Any],
    writer: Path,
    model: Path,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    """Transport the legacy v1 plan unchanged for compatibility wrappers."""
    with tempfile.TemporaryDirectory(prefix="moneywiz-coredata-") as temporary:
        plan_path = Path(temporary) / "plan.json"
        plan_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        completed = run(
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
    if completed.returncode:
        raise WriterClientError(
            completed.stderr.strip()
            or completed.stdout.strip()
            or "compatible Core Data writer failed"
        )
    return completed.stdout.strip()


class WriterClient:
    def __init__(self, writer: Path, model: Path, store: Path) -> None:
        self.writer, self.model, self.store = writer, model, store

    @contextmanager
    def _store_lock(self):
        """Pass one stable, store-inode-named sidecar flock to native writes."""
        try:
            with store_lock(self.store) as descriptor:
                yield descriptor
        except JournalError as exc:
            raise WriterClientError(str(exc)) from exc

    def _invoke(
        self, plan: dict[str, Any], *, recover: bool = False, lock_fd: int | None = None
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="moneywiz-write-") as temporary:
            plan_path = Path(temporary) / "plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            command = [
                str(self.writer),
                "--coredata-recover" if recover else "--coredata-write",
                "--store",
                str(self.store.resolve()),
                "--model",
                str(self.model),
                "--plan",
                str(plan_path),
            ]
            environment = dict(os.environ)
            kwargs: dict[str, Any] = {
                "capture_output": True,
                "text": True,
                "check": False,
                "env": environment,
            }
            if lock_fd is not None:
                environment["MONEYWIZ_WRITER_LOCK_FD"] = str(lock_fd)
                kwargs["pass_fds"] = (lock_fd,)
            completed = subprocess.run(
                command,
                check=False,
                **{key: value for key, value in kwargs.items() if key != "check"},
            )
        if completed.returncode:
            raise WriterClientError(
                completed.stderr.strip()
                or completed.stdout.strip()
                or "native writer failed without detail"
            )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise WriterClientError(
                "native writer returned no durable JSON receipt; outcome is unknown"
            ) from exc
        return self._validate_result(plan, result)

    @staticmethod
    def _validate_result(plan: dict[str, Any], result: object) -> dict[str, Any]:
        try:
            return validate_result(plan, result)
        except PlanValidationError as exc:
            raise WriterClientError(str(exc)) from exc

    def _execute(
        self,
        plan: dict[str, Any],
        journal: JournalStore,
        *,
        recover: bool,
        lock_fd: int,
    ) -> dict[str, Any]:
        try:
            result = self._invoke(plan, recover=recover, lock_fd=lock_fd)
            return self._validate_result(plan, result)
        except (
            WriterClientError,
            OSError,
            ValueError,
            subprocess.SubprocessError,
        ) as exc:
            journal.record_result(
                plan["plan_id"],
                {
                    "contract_version": 2,
                    "plan_id": plan["plan_id"],
                    "plan_digest": plan["plan_digest"],
                    "classification": "unknown",
                    "verified": False,
                    "operations": [],
                    "error": "native execution or independent receipt verification failed",
                },
                preserve_completed_at=True,
            )
            raise WriterClientError(
                "native outcome is unknown; inspect recovery before retrying"
            ) from exc

    @staticmethod
    def _matching_record(
        plan: dict[str, Any], journal: JournalStore
    ) -> dict[str, Any] | None:
        entry = journal._entry_path(plan["plan_id"])
        if not entry.exists() and not entry.is_symlink():
            return None
        record = journal.load(plan["plan_id"])
        if validate_plan(record.get("plan"))["plan_digest"] != plan["plan_digest"]:
            raise WriterClientError("existing journal evidence belongs to another plan")
        return record

    def apply(
        self, plan: dict[str, Any], reviewed_digest: str, journal: JournalStore
    ) -> dict[str, Any]:
        try:
            validated = validate_plan(plan)
        except PlanValidationError as exc:
            raise WriterClientError(str(exc)) from exc
        if reviewed_digest != validated["plan_digest"]:
            raise WriterClientError(
                "--reviewed-digest does not match the immutable plan"
            )
        with self._store_lock() as lock_fd, journal.writer_lock():
            require_moneywiz_stopped()
            record = self._matching_record(validated, journal)
            if record is None:
                journal.prepare(validated, self.store)
            else:
                result = self._execute(
                    validated, journal, recover=True, lock_fd=lock_fd
                )
                previously_verified = (
                    record.get("state") == "verified"
                    or record.get("ever_verified") is True
                )
                if previously_verified and result["classification"] != "noop":
                    result = {**result, "classification": "unknown", "verified": False}
                journal.record_result(
                    validated["plan_id"],
                    result,
                    preserve_completed_at=previously_verified,
                )
                if result["classification"] == "noop":
                    return result
                if result["classification"] != "retry_safe" or previously_verified:
                    raise WriterClientError(
                        "persisted state contradicts prior evidence; refusing replay"
                    )
            result = self._execute(validated, journal, recover=False, lock_fd=lock_fd)
            journal.record_result(validated["plan_id"], result)
            if result["classification"] not in {"applied", "noop"}:
                raise WriterClientError(
                    "native outcome is unresolved; run recovery before retrying"
                )
            return result

    def recover(self, plan: dict[str, Any], journal: JournalStore) -> dict[str, Any]:
        validated = validate_plan(plan)
        with self._store_lock() as lock_fd, journal.writer_lock():
            require_moneywiz_stopped()
            record = self._matching_record(validated, journal)
            if record is None:
                raise WriterClientError("no prepared journal exists for this plan")
            result = self._execute(validated, journal, recover=True, lock_fd=lock_fd)
            previously_verified = (
                record.get("state") == "verified" or record.get("ever_verified") is True
            )
            if previously_verified and result["classification"] != "noop":
                result = {**result, "classification": "unknown", "verified": False}
            journal.record_result(
                validated["plan_id"], result, preserve_completed_at=previously_verified
            )
            return result
