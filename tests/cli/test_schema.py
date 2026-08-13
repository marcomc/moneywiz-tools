import json
import os
import shutil
import subprocess
from pathlib import Path


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def _write_executable(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    path.chmod(0o755)


def test_schema_outputs(tmp_path, moneywiz_command: list[str]):
    out_md = tmp_path / "DB-SCHEMA.md"
    out_json = tmp_path / "schema.json"
    run(
        [
            *moneywiz_command,
            "schema",
            "--out-md",
            str(out_md),
            "--out-json",
            str(out_json),
        ]
    )
    assert out_md.exists() and out_md.stat().st_size > 0
    assert out_json.exists() and out_json.stat().st_size > 0
    data = json.loads(out_json.read_text())
    assert isinstance(data, list)
    # Expect to see Z_PRIMARYKEY table in dump
    assert any(t.get("name") == "Z_PRIMARYKEY" for t in data)


def test_source_schema_defaults_remain_in_checkout(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    source_root = tmp_path / "source"
    source_root.mkdir()
    shutil.copy2(repo_root / "moneywiz.sh", source_root / "moneywiz.sh")
    database = tmp_path / "store.sqlite"
    database.touch()
    _write_executable(
        source_root / ".venv/bin/python",
        """#!/usr/bin/env python3
import sys

output_format = sys.argv[sys.argv.index("--format") + 1]
print("# Source schema" if output_format == "md" else "[]")
""",
    )
    fake_bin = tmp_path / "bin"
    _write_executable(fake_bin / "uv", "#!/bin/sh\nexit 0\n")
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}:{env['PATH']}",
            "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
        }
    )

    result = subprocess.run(
        [str(source_root / "moneywiz.sh"), "--db", str(database), "schema"],
        cwd="/tmp",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (source_root / "doc/DB-SCHEMA.md").read_text() == "# Source schema\n"
    assert (source_root / "doc/schema.json").read_text() == "[]\n"
    assert not (tmp_path / "xdg-data").exists()
