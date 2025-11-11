import json
import subprocess
from pathlib import Path


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)


def test_transactions_all_fields_json():
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "moneywiz.sh"
    # Use a known account id from the test DB; request one row
    proc = run(["bash", str(script), "transactions", "--account", "5309", "--limit", "1", "--all-fields", "--format", "json"])
    data = json.loads(proc.stdout)
    assert isinstance(data, list) and len(data) >= 1
    item = data[0]
    # Should include a type marker and raw payload
    assert "__type__" in item
    assert "__raw" in item and isinstance(item["__raw"], dict)
    # Raw DB columns are not merged into top-level; available under __raw_all
    assert "__raw_all" in item and isinstance(item["__raw_all"], dict)
    # Basic keys still present
    for k in ("id", "datetime", "amount", "description"):
        assert k in item
