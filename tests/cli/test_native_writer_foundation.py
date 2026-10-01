import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def native_crash_probe(tmp_path_factory: pytest.TempPathFactory) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    executable = tmp_path_factory.mktemp("native-crash-probe") / "probe"
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
    return executable


@pytest.mark.parametrize(
    ("crash_flag", "expected_exit", "expected_recovery"),
    [
        ("--crash-before-save", 86, "retry_safe"),
        ("--crash-after-save", 87, "noop"),
    ],
)
def test_native_sqlite_crash_recovery_classifies_persisted_boundary(
    native_crash_probe: Path,
    tmp_path: Path,
    crash_flag: str,
    expected_exit: int,
    expected_recovery: str,
) -> None:
    store = tmp_path / "synthetic.sqlite"
    crashed = subprocess.run(
        [str(native_crash_probe), crash_flag, str(store)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert crashed.returncode == expected_exit

    recovered = subprocess.run(
        [str(native_crash_probe), "--recover", str(store)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert recovered.returncode == 0, recovered.stderr
    assert recovered.stdout.strip() == expected_recovery
