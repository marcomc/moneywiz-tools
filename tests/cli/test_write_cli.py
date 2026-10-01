"""The write dispatcher must keep inspection independent of stores and hosts."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import write
from test_write_plan import plan


@pytest.mark.parametrize("command", ["validate", "apply"])
def test_plan_inspection_never_resolves_runtime_or_creates_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    source = tmp_path / "plan.json"
    source.write_text(json.dumps(plan()))
    journal = tmp_path / "journal"
    monkeypatch.setenv("MONEYWIZ_JOURNAL_DIR", str(journal))
    monkeypatch.setattr(
        write, "_client", lambda *_args: pytest.fail("inspection resolved a writer")
    )
    assert write.main([command, "--plan", str(source)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "planned"
    assert len(output["plan_digest"]) == 64
    assert not journal.exists()


def test_apply_without_reviewed_digest_stops_before_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "plan.json"
    source.write_text(json.dumps(plan()))
    monkeypatch.setattr(
        write,
        "_client",
        lambda *_args: pytest.fail("unreviewed apply resolved a writer"),
    )
    assert write.main(["apply", "--plan", str(source), "--apply"]) == 2
    assert "reviewed-digest" in json.loads(capsys.readouterr().err)["message"]


@pytest.mark.parametrize("command", ["locations", "journal", "cleanup"])
def test_discovery_needs_no_database_and_creates_no_private_state(
    tmp_path: Path, command: str
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    journal = tmp_path / "uncreated-journal"
    environment = dict(os.environ, HOME=str(home), MONEYWIZ_JOURNAL_DIR=str(journal))
    completed = subprocess.run(
        [
            str(ROOT / "moneywiz.sh"),
            "--db",
            str(tmp_path / "missing.sqlite"),
            "write",
            command,
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert isinstance(json.loads(completed.stdout), dict)
    assert not journal.exists()
