import subprocess
from pathlib import Path


def test_coredata_writer_enforces_payee_ownership(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    executable = tmp_path / "moneywiz-tools-host-ownership-tests"
    result = subprocess.run(
        [
            "swiftc",
            "-parse-as-library",
            "-D",
            "MONEYWIZ_TOOLS_TESTING",
            str(repo_root / "scripts/moneywiz_tools_host.swift"),
            str(repo_root / "tests/swift/moneywiz_tools_host_ownership_tests.swift"),
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    completed = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "host ownership tests passed" in completed.stdout
