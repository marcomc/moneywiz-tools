import subprocess


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


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
