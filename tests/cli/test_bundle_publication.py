import os
import shlex
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_NAME = "MoneyWiz Tools.app"
DEVELOPMENT_ONLY_PROGRAMS = (
    "scripts/run_tests.sh",
    "scripts/sanitize_test_db.py",
    "scripts/shell_examples_test.py",
)
REQUIRED_DISPATCHER_PROGRAMS = (
    "scripts/accounts.py",
    "scripts/categories.py",
    "scripts/compatibility.py",
    "scripts/compatibility_matrix.json",
    "scripts/holdings.py",
    "scripts/introspect_db.py",
    "scripts/merge_duplicate_payees.py",
    "scripts/payees.py",
    "scripts/reassign_payees_by_id.py",
    "scripts/record.py",
    "scripts/run_moneywiz_cli.py",
    "scripts/stats.py",
    "scripts/summary.py",
    "scripts/tags.py",
    "scripts/transactions.py",
    "scripts/users.py",
)


def _write_executable(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    path.chmod(0o755)


def _prepare_source_tree(destination: Path) -> Path:
    source_root = destination / "source"
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    for encoded_path in tracked:
        if not encoded_path:
            continue
        relative_path = Path(os.fsdecode(encoded_path))
        source = REPO_ROOT / relative_path
        target = source_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    subprocess.run(["git", "init", "--quiet"], cwd=source_root, check=True)
    subprocess.run(["git", "add", "--all"], cwd=source_root, check=True)

    (source_root / "tests/test_db.sqlite").write_bytes(b"private database")
    (source_root / "tests/test_db.sqlite-wal").write_bytes(b"private wal")
    (source_root / "tests/test_db.sqlite-shm").write_bytes(b"private shm")
    (source_root / "scripts/private-build.log").write_text("private log")
    (source_root / "scripts/untracked-runtime.py").write_text("PRIVATE = True\n")
    (source_root / "scripts/__pycache__").mkdir()
    (source_root / "scripts/__pycache__/users.cpython-311.pyc").write_bytes(
        b"private cache"
    )
    (source_root / "doc/untracked-notes.md").write_text("private notes\n")

    tracked_script = source_root / "scripts/users.py"
    tracked_script.write_text(
        tracked_script.read_text() + "\n# current tracked worktree payload\n"
    )
    return source_root


@pytest.fixture
def install_environment(tmp_path: Path) -> dict[str, Path | dict[str, str]]:
    source_root = _prepare_source_tree(tmp_path)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_tool = fake_bin / "fake-tool"
    _write_executable(
        fake_tool,
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import os
            import sys
            from pathlib import Path


            def executable(path: Path, contents: str = "#!/bin/sh\\nexit 0\\n") -> None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents)
                path.chmod(0o755)


            tool = Path(sys.argv[0]).name
            args = sys.argv[1:]

            if tool == "uv":
                if args == ["--version"]:
                    print("uv 0.1.0")
                elif args[:2] == ["python", "install"]:
                    install_dir = Path(args[args.index("--install-dir") + 1])
                    executable(
                        install_dir / "fake" / "bin" / "python3.11",
                        "#!/usr/bin/env python3\\n"
                        "import sys\\n"
                        "output_format = sys.argv[sys.argv.index('--format') + 1]\\n"
                        "print('# Fake schema' if output_format == 'md' else '[]')\\n",
                    )
                elif args and args[0] == "venv":
                    executable(Path(args[-1]) / "bin" / "python")
                elif args and args[0] == "export":
                    output = Path(args[args.index("--output-file") + 1])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text("")
                elif args[:2] != ["pip", "install"]:
                    raise SystemExit(f"unexpected uv arguments: {args}")
            elif tool == "swiftc":
                if args == ["--version"]:
                    print("Apple Swift version 6.0")
                elif os.environ.get("FAKE_SWIFTC_FAIL") == "1":
                    print("injected swiftc failure", file=sys.stderr)
                    raise SystemExit(42)
                else:
                    executable(Path(args[args.index("-o") + 1]))
            elif tool == "mv":
                source = args[-2]
                destination = args[-1]
                failure_destination = os.environ.get("FAIL_PROMOTION_DEST")
                failure_marker = Path(os.environ.get("FAIL_PROMOTION_MARKER", "/dev/null"))
                is_staged_bundle = ".staging." in source and not source.endswith(".previous")
                if (
                    failure_destination == destination
                    and is_staged_bundle
                    and not failure_marker.exists()
                ):
                    failure_marker.write_text("failed")
                    print("injected bundle promotion failure", file=sys.stderr)
                    raise SystemExit(43)
                os.execv("/bin/mv", ["/bin/mv", *args])
            else:
                raise SystemExit(f"unexpected fake tool name: {tool}")
            """
        ),
    )
    for name in ("uv", "swiftc", "mv"):
        (fake_bin / name).symlink_to(fake_tool)

    home = tmp_path / "home"
    apps = home / "Applications"
    prefix = home / ".local"
    app_bundle = apps / APP_NAME
    launcher = app_bundle / "Contents" / "Resources" / "runtime" / "moneywiz.sh"
    command = prefix / "bin" / "moneywiz"
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}:{env['PATH']}",
        }
    )
    return {
        "apps": apps,
        "prefix": prefix,
        "app_bundle": app_bundle,
        "launcher": launcher,
        "command": command,
        "env": env,
        "tmp_path": tmp_path,
        "source_root": source_root,
    }


def _seed_previous_install(paths: dict[str, Path | dict[str, str]]) -> None:
    app_bundle = paths["app_bundle"]
    launcher = paths["launcher"]
    command = paths["command"]
    assert isinstance(app_bundle, Path)
    assert isinstance(launcher, Path)
    assert isinstance(command, Path)
    (app_bundle / "previous-install").mkdir(parents=True)
    _write_executable(launcher, "#!/bin/sh\necho previous-install\n")
    command.parent.mkdir(parents=True)
    command.symlink_to(launcher)


def _run_make(
    paths: dict[str, Path | dict[str, str]],
    target: str,
    **extra_env: str,
) -> subprocess.CompletedProcess[str]:
    apps = paths["apps"]
    prefix = paths["prefix"]
    env = paths["env"]
    tmp_path = paths["tmp_path"]
    source_root = paths["source_root"]
    assert isinstance(apps, Path)
    assert isinstance(prefix, Path)
    assert isinstance(env, dict)
    assert isinstance(tmp_path, Path)
    assert isinstance(source_root, Path)
    run_env = env.copy()
    run_env.update(extra_env)
    return subprocess.run(
        [
            "/usr/bin/make",
            "--no-print-directory",
            target,
            f"APP_BUNDLE_DIR={apps}",
            f"PREFIX={prefix}",
            f"USER_CONFIG_DIR={tmp_path / 'config'}",
        ],
        cwd=source_root,
        env=run_env,
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_previous_install(paths: dict[str, Path | dict[str, str]]) -> None:
    app_bundle = paths["app_bundle"]
    launcher = paths["launcher"]
    command = paths["command"]
    apps = paths["apps"]
    assert isinstance(app_bundle, Path)
    assert isinstance(launcher, Path)
    assert isinstance(command, Path)
    assert isinstance(apps, Path)
    assert (app_bundle / "previous-install").is_dir()
    assert "previous-install" in launcher.read_text()
    assert command.is_symlink()
    assert command.readlink() == launcher
    assert list(apps.glob(f".{APP_NAME}.staging.*")) == []


def _run_installed(
    paths: dict[str, Path | dict[str, str]],
    *arguments: str,
    **extra_env: str,
) -> subprocess.CompletedProcess[str]:
    command = paths["command"]
    env = paths["env"]
    assert isinstance(command, Path)
    assert isinstance(env, dict)
    run_env = env.copy()
    run_env.update(extra_env)
    return subprocess.run(
        [str(command), *arguments],
        env=run_env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_installed_schema_uses_user_data_defaults_and_explicit_overrides(
    install_environment: dict[str, Path | dict[str, str]],
) -> None:
    result = _run_make(install_environment, "install")
    assert result.returncode == 0, result.stderr

    tmp_path = install_environment["tmp_path"]
    app_bundle = install_environment["app_bundle"]
    assert isinstance(tmp_path, Path)
    assert isinstance(app_bundle, Path)
    database = tmp_path / "live.sqlite"
    database.touch()
    xdg_data_home = tmp_path / "xdg-data"

    result = _run_installed(
        install_environment,
        "--db",
        str(database),
        "schema",
        XDG_DATA_HOME=str(xdg_data_home),
    )

    assert result.returncode == 0, result.stderr
    default_directory = xdg_data_home / "moneywiz-tools/schema"
    assert (default_directory / "DB-SCHEMA.md").read_text() == "# Fake schema\n"
    assert (default_directory / "schema.json").read_text() == "[]\n"
    bundled_schema = app_bundle / "Contents/Resources/runtime/doc/DB-SCHEMA.md"
    assert "Fake schema" not in bundled_schema.read_text()

    explicit_markdown = tmp_path / "explicit/schema.md"
    explicit_json = tmp_path / "explicit/schema.json"
    result = _run_installed(
        install_environment,
        "--db",
        str(database),
        "schema",
        "--out-md",
        str(explicit_markdown),
        "--out-json",
        str(explicit_json),
        XDG_DATA_HOME=str(tmp_path / "other-data"),
    )

    assert result.returncode == 0, result.stderr
    assert explicit_markdown.read_text() == "# Fake schema\n"
    assert explicit_json.read_text() == "[]\n"
    assert not (tmp_path / "other-data").exists()

    result = _run_installed(
        install_environment,
        "--db",
        str(database),
        "schema",
        XDG_DATA_HOME="",
    )

    assert result.returncode == 0, result.stderr
    home_default = tmp_path / "home/.local/share/moneywiz-tools/schema"
    assert (home_default / "DB-SCHEMA.md").read_text() == "# Fake schema\n"
    assert (home_default / "schema.json").read_text() == "[]\n"


@pytest.mark.parametrize("option", ["--out-md", "--out-json"])
def test_installed_schema_rejects_missing_output_path(
    install_environment: dict[str, Path | dict[str, str]], option: str
) -> None:
    result = _run_make(install_environment, "install")
    assert result.returncode == 0, result.stderr
    tmp_path = install_environment["tmp_path"]
    assert isinstance(tmp_path, Path)
    database = tmp_path / "live.sqlite"
    database.touch()

    result = _run_installed(
        install_environment, "--db", str(database), "schema", option
    )

    assert result.returncode == 2
    assert f"Error: {option} requires a path" in result.stderr
    assert "unbound variable" not in result.stderr


@pytest.mark.parametrize("command_name", ["create-test-db", "sanitize-test-db"])
def test_installed_dispatcher_rejects_source_only_database_commands(
    install_environment: dict[str, Path | dict[str, str]], command_name: str
) -> None:
    result = _run_make(install_environment, "install")
    assert result.returncode == 0, result.stderr

    result = _run_installed(install_environment, command_name)

    assert result.returncode == 2
    assert f"Error: {command_name} is a source-checkout-only" in result.stderr


def test_reinstall_build_failure_preserves_previous_install(
    install_environment: dict[str, Path | dict[str, str]],
) -> None:
    _seed_previous_install(install_environment)

    result = _run_make(
        install_environment,
        "reinstall",
        FAKE_SWIFTC_FAIL="1",
    )

    assert result.returncode != 0
    assert "injected swiftc failure" in result.stderr
    _assert_previous_install(install_environment)


def test_promotion_failure_restores_previous_install(
    install_environment: dict[str, Path | dict[str, str]],
) -> None:
    _seed_previous_install(install_environment)
    app_bundle = install_environment["app_bundle"]
    tmp_path = install_environment["tmp_path"]
    assert isinstance(app_bundle, Path)
    assert isinstance(tmp_path, Path)

    result = _run_make(
        install_environment,
        "reinstall",
        FAIL_PROMOTION_DEST=str(app_bundle),
        FAIL_PROMOTION_MARKER=str(tmp_path / "promotion-failed"),
    )

    assert result.returncode != 0
    assert "failed to publish the staged bundle" in result.stderr
    _assert_previous_install(install_environment)


def test_next_run_recovers_interrupted_promotion_before_build_checks(
    install_environment: dict[str, Path | dict[str, str]],
) -> None:
    _seed_previous_install(install_environment)
    app_bundle = install_environment["app_bundle"]
    apps = install_environment["apps"]
    assert isinstance(app_bundle, Path)
    assert isinstance(apps, Path)
    recovery_bundle = apps / f".{APP_NAME}.previous"
    app_bundle.rename(recovery_bundle)

    result = _run_make(
        install_environment,
        "reinstall",
        FAKE_SWIFTC_FAIL="1",
    )

    assert result.returncode != 0
    assert "ok restored interrupted bundle promotion" in result.stdout
    assert not recovery_bundle.exists()
    _assert_previous_install(install_environment)


def test_successful_reinstall_publishes_complete_bundle_and_command(
    install_environment: dict[str, Path | dict[str, str]],
) -> None:
    _seed_previous_install(install_environment)
    app_bundle = install_environment["app_bundle"]
    launcher = install_environment["launcher"]
    command = install_environment["command"]
    apps = install_environment["apps"]
    assert isinstance(app_bundle, Path)
    assert isinstance(launcher, Path)
    assert isinstance(command, Path)
    assert isinstance(apps, Path)

    result = _run_make(install_environment, "reinstall")

    assert result.returncode == 0, result.stderr
    assert not (app_bundle / "previous-install").exists()
    assert (app_bundle / "Contents" / "Info.plist").is_file()
    assert (app_bundle / "Contents" / "MacOS" / "MoneyWizTools").stat().st_mode & 0o111
    assert launcher.stat().st_mode & 0o111
    assert (
        app_bundle
        / "Contents"
        / "Resources"
        / "runtime"
        / "python"
        / "venv"
        / "bin"
        / "python"
    ).stat().st_mode & 0o111
    python_link = (
        app_bundle
        / "Contents"
        / "Resources"
        / "runtime"
        / "python"
        / "venv"
        / "bin"
        / "python"
    )
    assert python_link.is_symlink()
    assert not python_link.readlink().is_absolute()
    assert command.is_symlink()
    assert command.readlink() == launcher
    assert list(apps.glob(f".{APP_NAME}.staging.*")) == []

    runtime = app_bundle / "Contents/Resources/runtime"
    assert (runtime / "scripts/users.py").is_file()
    assert (
        "current tracked worktree payload" in (runtime / "scripts/users.py").read_text()
    )
    assert (runtime / "doc/BUNDLE-INSTALLATION.md").is_file()
    assert (runtime / ".moneywizrc.example").is_file()
    for relative_path in REQUIRED_DISPATCHER_PROGRAMS:
        assert (runtime / relative_path).is_file()
    for relative_path in DEVELOPMENT_ONLY_PROGRAMS:
        assert not (runtime / relative_path).exists()
    assert not (runtime / "tests").exists()
    assert not (runtime / "tests/test_db.sqlite").exists()
    assert not (runtime / "tests/test_db.sqlite-wal").exists()
    assert not (runtime / "tests/test_db.sqlite-shm").exists()
    assert not (runtime / "scripts/private-build.log").exists()
    assert not (runtime / "scripts/untracked-runtime.py").exists()
    assert not (runtime / "scripts/__pycache__").exists()
    assert not (runtime / "doc/untracked-notes.md").exists()

    python_link = runtime / "python/venv/bin/python"
    _write_executable(
        python_link.resolve(),
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n',
    )
    database = install_environment["tmp_path"] / "dispatcher.sqlite"
    assert isinstance(database, Path)
    database.touch()
    dispatcher_result = _run_installed(
        install_environment,
        "--db",
        str(database),
        "compatibility",
        "--help",
    )
    assert dispatcher_result.returncode == 0, dispatcher_result.stderr
    assert "usage:" in dispatcher_result.stdout


def test_install_moneywiz_rejects_incomplete_bundle_before_relinking(
    install_environment: dict[str, Path | dict[str, str]],
) -> None:
    _seed_previous_install(install_environment)
    command = install_environment["command"]
    launcher = install_environment["launcher"]
    assert isinstance(command, Path)
    assert isinstance(launcher, Path)

    result = _run_make(install_environment, "install-moneywiz")

    assert result.returncode != 0
    assert "bundle is missing Contents/Info.plist" in result.stdout
    assert command.is_symlink()
    assert command.readlink() == launcher
