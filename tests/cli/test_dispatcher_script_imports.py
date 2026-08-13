import os
import plistlib
import shutil
import subprocess
import textwrap
import tomllib
from pathlib import Path


def _write_executable(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    path.chmod(0o755)


def test_source_version_flags_need_no_database_or_python(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    source_root = tmp_path / "nested/source"
    (source_root / "scripts").mkdir(parents=True)
    shutil.copy2(repo_root / "moneywiz.sh", source_root / "moneywiz.sh")
    shutil.copy2(
        repo_root / "scripts/MoneyWizTools-Info.plist",
        source_root / "scripts/MoneyWizTools-Info.plist",
    )
    with (repo_root / "pyproject.toml").open("rb") as project_file:
        expected_version = tomllib.load(project_file)["project"]["version"]
    with (tmp_path / "Info.plist").open("wb") as ancestor_plist:
        plistlib.dump({"CFBundleShortVersionString": "9.9.9"}, ancestor_plist)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".moneywizrc").write_text(f"db_path={tmp_path / 'missing.sqlite'}\n")
    env = os.environ.copy()
    env.update({"HOME": str(home), "PATH": "/usr/bin:/bin"})

    for option in ("--version", "-V"):
        result = subprocess.run(
            [str(source_root / "moneywiz.sh"), option],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == f"moneywiz {expected_version}\n"
        assert result.stderr == ""


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


def test_source_dispatcher_help_does_not_require_configured_database(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    source_root = tmp_path / "source"
    source_root.mkdir()
    shutil.copy2(repo_root / "moneywiz.sh", source_root / "moneywiz.sh")
    (source_root / "scripts").mkdir()
    fake_python_log = tmp_path / "python.log"
    _write_executable(
        source_root / ".venv/bin/python",
        textwrap.dedent(
            """\
            #!/bin/sh
            printf '%s\n' "$@" > "${FAKE_PYTHON_LOG}"
            echo 'usage: delegated command'
            """
        ),
    )
    fake_bin = tmp_path / "bin"
    _write_executable(fake_bin / "uv", "#!/bin/sh\nexit 0\n")
    home = tmp_path / "home"
    home.mkdir()
    missing_database = tmp_path / "missing.sqlite"
    (home / ".moneywizrc").write_text(f"db_path={missing_database}\n")
    env = os.environ.copy()
    env.update(
        {
            "FAKE_PYTHON_LOG": str(fake_python_log),
            "HOME": str(home),
            "PATH": f"{fake_bin}:{env['PATH']}",
        }
    )
    delegated_commands = (
        "users",
        "accounts",
        "categories",
        "payees",
        "tags",
        "transactions",
        "holdings",
        "reassign-payees-by-id",
        "merge-duplicate-payees",
        "compatibility",
        "summary",
        "stats",
        "record",
        "shell",
        "sanitize-test-db",
    )

    for command in delegated_commands:
        for help_option in ("--help", "-h"):
            result = subprocess.run(
                [str(source_root / "moneywiz.sh"), command, help_option],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, (command, help_option, result.stderr)
            assert "Database file not found" not in result.stderr
            if command == "shell" and help_option == "-h":
                assert fake_python_log.read_text().splitlines()[-1] == "--help"

    for command in ("schema", "create-test-db"):
        for help_option in ("--help", "-h"):
            result = subprocess.run(
                [str(source_root / "moneywiz.sh"), command, help_option],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, (command, help_option, result.stderr)
            assert "Usage:" in result.stdout
            assert "Database file not found" not in result.stderr

    result = subprocess.run(
        [str(source_root / "moneywiz.sh"), "users"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Database file not found" in result.stderr


def test_readme_categories_example_is_executable() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    documented_command = next(
        line
        for line in (repo_root / "README.md").read_text().splitlines()
        if line.startswith("moneywiz categories ")
    )

    assert documented_command == "moneywiz categories --user 1"
    result = subprocess.run(
        [
            str(repo_root / "moneywiz.sh"),
            "--db",
            str(repo_root / "tests/test_db.sqlite"),
            *documented_command.split()[1:],
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "the following arguments are required: --user" not in result.stderr


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
