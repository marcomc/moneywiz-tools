import json
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)


def test_users_json():
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "moneywiz.sh"
    # Use json for easy parsing
    proc = run(["bash", str(script), "users", "--format", "json"])
    data = json.loads(proc.stdout)
    assert isinstance(data, list)
    assert all("id" in x and "login_name" in x for x in data)
