import os
import plistlib
import shutil
import subprocess
import textwrap
import tomllib
from pathlib import Path

import pytest


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


def test_concepts_links_to_pinned_installed_dependency_source() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    with (repo_root / "pyproject.toml").open("rb") as project_file:
        dependencies = tomllib.load(project_file)["project"]["dependencies"]
    moneywiz_api_dependency = next(
        dependency
        for dependency in dependencies
        if dependency.startswith("moneywiz-api @ ")
    )
    revision = moneywiz_api_dependency.rsplit("@", maxsplit=1)[1]
    pinned_source_url = (
        "https://github.com/marcomc/moneywiz-api/blob/"
        f"{revision}/src/moneywiz_api/utils.py#L6-L15"
    )
    concepts = (repo_root / "doc/CONCEPTS.md").read_text()
    dependency_ticket = (
        repo_root / "doc/wayfinder/tickets/pinned-dependency-bundle-mechanism.md"
    ).read_text()
    normalized_ticket = " ".join(dependency_ticket.split())
    wayfinder_map = (repo_root / "doc/wayfinder/MAP.md").read_text()
    frontier = wayfinder_map.partition("## Frontier\n")[2].partition("\n## ")[0]

    assert "installed `moneywiz_api` module" in concepts
    assert pinned_source_url in concepts
    assert "moneywiz-api/src" not in concepts
    assert "**Status:** Closed" in dependency_ticket
    assert "## Resolution" in dependency_ticket
    assert revision in dependency_ticket
    assert "`uv.lock` resolves that same commit" in normalized_ticket
    assert "`uv export --frozen`" in dependency_ticket
    assert "`uv pip install`" in dependency_ticket
    assert "`Contents/Resources/runtime/python/venv`" in dependency_ticket
    assert "No local checkout is required, consumed, or bundled." in normalized_ticket
    assert "tickets/pinned-dependency-bundle-mechanism.md" not in frontier


def test_architecture_docs_bound_open_work_to_future_writer_evolution() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    srs = (repo_root / "doc/SRS.md").read_text()
    concepts = (repo_root / "doc/CONCEPTS.md").read_text()
    wayfinder_map = (repo_root / "doc/wayfinder/MAP.md").read_text()
    upstream_ticket = (
        repo_root / "doc/wayfinder/tickets/upstream-v1.0.8-intake.md"
    ).read_text()
    writer_ticket = (
        repo_root / "doc/wayfinder/tickets/python-coredata-writer-contract.md"
    ).read_text()
    python_writer = (repo_root / "scripts/reassign_payees_by_id.py").read_text()
    swift_host = (repo_root / "scripts/moneywiz_tools_host.swift").read_text()

    assert "Generic write helpers" not in srs
    assert "only verified live write is payee reassignment" in srs
    assert "Core Data owns `Z_OPT` initialization and updates" in concepts
    assert "creation sequence still needs a pre/post capture" not in concepts

    assert "Do not perform the migration while charting the map" not in wayfinder_map
    assert "No subagent orchestration is available" not in wayfinder_map
    assert "exact migration sequence" not in wayfinder_map
    assert "contract version 1" in wayfinder_map

    for ticket in (upstream_ticket, writer_ticket):
        assert "**Status:** Open" in ticket
    assert "does not gate either implemented decision" in upstream_ticket
    assert "Future read-API pin updates" in upstream_ticket
    assert "## Implemented baseline" in writer_ticket
    assert "`contract_version` 1" in writer_ticket
    assert "Future writer operations and the GUI boundary" in writer_ticket

    assert 'writer_payload["contract_version"] = 1' in python_writer
    assert 'case contractVersion = "contract_version"' in swift_host
    assert "guard plan.contractVersion == 1" in swift_host
    for result_field in (
        'case createdPayees = "created_payees"',
        'case reassignedTransactions = "reassigned_transactions"',
        'case mergedPayees = "merged_payees"',
        'case migratedRelationships = "migrated_relationships"',
    ):
        assert result_field in swift_host


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
    assert source_database.read_bytes() == b"source database"
    assert "scripts/sanitize_test_db.py" in python_log.read_text()


@pytest.mark.parametrize(
    ("store_state", "expected_kind"),
    [
        ("current", "current"),
        ("legacy", "legacy"),
        ("both", "current"),
        ("neither", "commented-current"),
    ],
)
def test_setup_and_test_db_creation_share_store_discovery(
    tmp_path: Path, store_state: str, expected_kind: str
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    source_root = tmp_path / "source"
    source_root.mkdir()
    shutil.copy2(repo_root / "moneywiz.sh", source_root / "moneywiz.sh")
    _write_executable(source_root / ".venv/bin/python", "#!/bin/sh\nexit 0\n")
    fake_bin = tmp_path / "bin"
    _write_executable(fake_bin / "uv", "#!/bin/sh\nexit 0\n")
    home = tmp_path / "home"
    home.mkdir()
    current_store = (
        home
        / "Library/Containers/com.moneywiz.personalfinance-setapp/Data/Library"
        / "Application Support/MoneyWiz_iCloud.sqlite"
    )
    legacy_store = (
        home
        / "Library/Containers/com.moneywiz.personalfinance-setapp/Data/Documents"
        / ".AppData/ipadMoneyWiz.sqlite"
    )
    if store_state in {"current", "both"}:
        current_store.parent.mkdir(parents=True)
        current_store.write_bytes(b"current store")
    if store_state in {"legacy", "both"}:
        legacy_store.parent.mkdir(parents=True)
        legacy_store.write_bytes(b"legacy store")
    expected_store = current_store if expected_kind != "legacy" else legacy_store
    env = os.environ.copy()
    env.update({"HOME": str(home), "PATH": f"{fake_bin}:{env['PATH']}"})
    dispatcher = source_root / "moneywiz.sh"

    setup = subprocess.run(
        [str(dispatcher), "--setup"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert setup.returncode == 0, setup.stderr
    config_path = home / ".moneywizrc"
    expected_config = (
        f"# db_path={expected_store}"
        if expected_kind == "commented-current"
        else f"db_path={expected_store}"
    )
    assert expected_config in config_path.read_text()
    config_path.write_text("db_path=/preserved.sqlite\n")
    repeated_setup = subprocess.run(
        [str(dispatcher), "--setup"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert repeated_setup.returncode == 0, repeated_setup.stderr
    assert config_path.read_text() == "db_path=/preserved.sqlite\n"

    config_path.unlink()
    created = subprocess.run(
        [str(dispatcher), "create-test-db"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if expected_kind == "commented-current":
        assert created.returncode == 1
        assert f"source database not found: {current_store}" in created.stderr
    else:
        assert created.returncode == 0, created.stderr
        assert (source_root / "tests/test_db.sqlite").read_bytes() == (
            expected_store.read_bytes()
        )

    explicit_store = tmp_path / "explicit.sqlite"
    explicit_store.write_bytes(b"explicit store")
    explicit = subprocess.run(
        [str(dispatcher), "--db", str(explicit_store), "create-test-db"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert explicit.returncode == 0, explicit.stderr
    assert (source_root / "tests/test_db.sqlite").read_bytes() == b"explicit store"
