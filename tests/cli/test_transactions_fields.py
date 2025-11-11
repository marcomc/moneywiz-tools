import subprocess
from pathlib import Path


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)


def test_transactions_fields_header():
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "moneywiz.sh"
    proc = run([
        "bash",
        str(script),
        "transactions",
        "--account",
        "5309",
        "--limit",
        "1",
        "--fields",
        "id,account,account_name,payee,payee_name,amount,original_currency,original_amount",
    ])
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines
    header = lines[0]
    # Split on any whitespace to accommodate formatted table
    assert header.split() == [
        "id",
        "account",
        "account_name",
        "payee",
        "payee_name",
        "amount",
        "original_currency",
        "original_amount",
    ]
