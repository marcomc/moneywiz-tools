import subprocess
from pathlib import Path


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)


def test_payees_sort_by_name_header_and_order():
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "moneywiz.sh"
    # Run with and without sort to ensure it doesn't crash and has header
    proc = run(["bash", str(script), "payees", "--user", "2", "--sort-by-name"])
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines
    header = lines[0].split()
    assert header == ["user", "id", "name"]
    # Check sorted order lexicographically for first few data rows
    names = [ln.split(maxsplit=2)[2] for ln in lines[1:6] if len(ln.split(maxsplit=2)) == 3]
    assert names == sorted(names, key=lambda s: s.lower())

