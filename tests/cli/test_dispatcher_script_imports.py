import subprocess
from pathlib import Path


def test_dispatcher_can_load_scripts_with_sibling_imports_from_other_directory(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    dispatcher = repo_root / "moneywiz.sh"
    readable_placeholder = tmp_path / "placeholder.sqlite"
    readable_placeholder.touch()

    result = subprocess.run(
        [
            "bash",
            str(dispatcher),
            "--db",
            str(readable_placeholder),
            "merge-duplicate-payees",
            "--help",
        ],
        cwd="/tmp",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Merge exact-normalized payee duplicates" in result.stdout
    assert "ModuleNotFoundError" not in result.stderr
