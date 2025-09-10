import json
import subprocess
from pathlib import Path


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)


def test_schema_outputs(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "moneywiz.sh"
    out_md = tmp_path / "DB-SCHEMA.md"
    out_json = tmp_path / "schema.json"
    run(["bash", str(script), "schema", "--out-md", str(out_md), "--out-json", str(out_json)])
    assert out_md.exists() and out_md.stat().st_size > 0
    assert out_json.exists() and out_json.stat().st_size > 0
    data = json.loads(out_json.read_text())
    assert isinstance(data, list)
    # Expect to see Z_PRIMARYKEY table in dump
    assert any(t.get("name") == "Z_PRIMARYKEY" for t in data)

