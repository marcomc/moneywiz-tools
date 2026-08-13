import os
import shutil
import subprocess
from pathlib import Path


def _write_executable(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    path.chmod(0o755)


def test_dispatcher_can_load_scripts_with_sibling_imports_from_other_directory(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    dispatcher = repo_root / "moneywiz.sh"
    readable_placeholder = tmp_path / "placeholder.sqlite"
    readable_placeholder.touch()

    result = subprocess.run(
        [
            str(dispatcher),
            "--db",
            str(readable_placeholder),
            "merge-duplicate-payees",
            "--help",
        ],
        cwd="/tmp",
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Merge exact-normalized payee duplicates" in result.stdout
    assert "ModuleNotFoundError" not in result.stderr


def test_source_dispatcher_preserves_test_database_workflow(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    source_root = tmp_path / "source"
    source_root.mkdir()
    shutil.copy2(repo_root / "moneywiz.sh", source_root / "moneywiz.sh")
    (source_root / "scripts").mkdir()
    (source_root / "scripts/sanitize_test_db.py").touch()
    source_database = tmp_path / "live.sqlite"
    source_database.write_bytes(b"source database")
    home = tmp_path / "home"
    home.mkdir()
    (home / ".moneywizrc").write_text(f"db_path={source_database}\n")
    python_log = tmp_path / "python.log"
    _write_executable(
        source_root / ".venv/bin/python",
        """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

Path(os.environ["FAKE_PYTHON_LOG"]).write_text("\\n".join(sys.argv))
""",
    )
    fake_bin = tmp_path / "bin"
    _write_executable(fake_bin / "uv", "#!/bin/sh\nexit 0\n")
    env = os.environ.copy()
    env.update(
        {
            "FAKE_PYTHON_LOG": str(python_log),
            "HOME": str(home),
            "PATH": f"{fake_bin}:{env['PATH']}",
        }
    )
    dispatcher = source_root / "moneywiz.sh"

    created = subprocess.run(
        [str(dispatcher), "create-test-db"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    sanitized = subprocess.run(
        [str(dispatcher), "sanitize-test-db"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert created.returncode == 0, created.stderr
    assert (source_root / "tests/test_db.sqlite").read_bytes() == b"source database"
    assert sanitized.returncode == 0, sanitized.stderr
    assert "scripts/sanitize_test_db.py" in python_log.read_text()
