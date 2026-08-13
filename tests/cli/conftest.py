from pathlib import Path

import pytest


@pytest.fixture
def moneywiz_command() -> list[str]:
    repo_root = Path(__file__).resolve().parents[2]
    return [
        "bash",
        str(repo_root / "moneywiz.sh"),
        "--db",
        str(repo_root / "tests/test_db.sqlite"),
    ]
