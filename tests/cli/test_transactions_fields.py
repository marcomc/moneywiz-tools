import json
import subprocess


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    # The legacy fixture contains unreadable transfers. Listing parsed rows is
    # supported, but the CLI must explicitly report that the read is partial.
    assert result.returncode == 3, result.stderr
    assert (
        json.loads(result.stderr.splitlines()[-1])["read_completeness"]["complete"]
        is False
    )
    return result


def test_transactions_fields_header(moneywiz_command: list[str]):
    proc = run(
        [
            *moneywiz_command,
            "transactions",
            "--account",
            "5309",
            "--limit",
            "1",
            "--fields",
            "id,account,account_name,payee,payee_name,amount,original_currency,original_amount",
        ]
    )
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
