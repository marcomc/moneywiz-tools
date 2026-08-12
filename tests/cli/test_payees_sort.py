import subprocess


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def test_payees_sort_by_name_header_and_order(moneywiz_command: list[str]):
    # Run with and without sort to ensure it doesn't crash and has header
    proc = run([*moneywiz_command, "payees", "--user", "2", "--sort-by-name"])
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines
    header = lines[0].split()
    assert header == ["user", "id", "name"]
    # Check sorted order lexicographically for first few data rows
    names = [
        ln.split(maxsplit=2)[2] for ln in lines[1:6] if len(ln.split(maxsplit=2)) == 3
    ]
    assert names == sorted(names, key=lambda s: s.lower())
