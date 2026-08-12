import json
import subprocess


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def test_users_json(moneywiz_command: list[str]):
    # Use json for easy parsing
    proc = run([*moneywiz_command, "users", "--format", "json"])
    data = json.loads(proc.stdout)
    assert isinstance(data, list)
    assert all("id" in x and "login_name" in x for x in data)
