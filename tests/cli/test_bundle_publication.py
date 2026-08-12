import os
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_NAME = "MoneyWiz Tools.app"


def _write_executable(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    path.chmod(0o755)


@pytest.fixture
def install_environment(tmp_path: Path) -> dict[str, Path | dict[str, str]]:
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
                    executable(install_dir / "fake" / "bin" / "python3.11")
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
    assert isinstance(apps, Path)
    assert isinstance(prefix, Path)
    assert isinstance(env, dict)
    assert isinstance(tmp_path, Path)
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
        cwd=REPO_ROOT,
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
