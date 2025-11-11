import subprocess
from pathlib import Path


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)


def test_transactions_list_fields_contains_core():
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "moneywiz.sh"
    proc = run(["bash", str(script), "transactions", "--account", "5309", "--limit", "5", "--list-fields"])
    cols = set(line.strip() for line in proc.stdout.splitlines() if line.strip())
    # Must include core columns and account_name
    for k in ("id", "datetime", "account", "account_name", "amount", "description"):
        assert k in cols

