import subprocess


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def test_transactions_list_fields_contains_core(moneywiz_command: list[str]):
    proc = run(
        [
            *moneywiz_command,
            "transactions",
            "--account",
            "5309",
            "--limit",
            "5",
            "--list-fields",
        ]
    )
    cols = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    # Must include core columns and account_name
    for k in ("id", "datetime", "account", "account_name", "amount", "description"):
        assert k in cols
