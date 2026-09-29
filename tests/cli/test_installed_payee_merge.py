"""Relocated W09 bundle plans and recovers a disposable payee merge."""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from test_native_payee_merge import inspect, store
from test_native_transaction_create import W01Runtime, w01_runtime


def test_relocated_bundle_merges_all_payee_references(
    w01_runtime: W01Runtime, tmp_path: Path
) -> None:
    configured = os.environ.get("MONEYWIZ_TEST_BUNDLE_PATH")
    if not configured:
        pytest.skip("set MONEYWIZ_TEST_BUNDLE_PATH for installed W09 evidence")
    source = Path(__file__).resolve().parents[2]
    relocated = tmp_path / "relocated" / "MoneyWiz Tools.app"
    relocated.parent.mkdir()
    shutil.copytree(Path(configured).resolve(), relocated, symlinks=True)
    launcher = relocated / "Contents/Resources/runtime/moneywiz.sh"
    sandbox = shutil.which("sandbox-exec")
    assert sandbox is not None
    profile = f'(version 1) (allow default) (deny file-read* (subpath "{source}"))'
    denied = subprocess.run([sandbox, "-p", profile, "/bin/cat", str(source / "README.md")],
                            capture_output=True, check=False)
    assert denied.returncode != 0

    db, seeded = store(w01_runtime, tmp_path)
    owner = seeded["owner_uri"].rsplit("/p", 1)[1]
    environment = dict(w01_runtime.environment)
    environment["MONEYWIZ_JOURNAL_DIR"] = str(tmp_path / "journal")
    for name in ("PYTHONPATH", "MONEYWIZ_TOOLS_HOST", "MONEYWIZ_CORE_DATA_WRITER"):
        environment.pop(name, None)

    def run(*arguments: str) -> dict:
        result = subprocess.run(
            [sandbox, "-p", profile, str(launcher), "--db", str(db), *arguments],
            cwd=tmp_path, env=environment, capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    plan_path = tmp_path / "installed-w09-plan.json"
    planned = run("payee", "merge", "--kind", "exact", "--source-gid", "w09-source",
                  "--survivor-gid", "w09-survivor", "--evidence-note",
                  "Reviewed synthetic duplicate", "--app", str(w01_runtime.app),
                  "--model", str(w01_runtime.model), "--owner", owner,
                  "--plan", str(plan_path))
    assert planned["status"] == "planned"
    digest = planned["plan_digest"]
    assert run("write", "validate", "--plan", str(plan_path))["plan_digest"] == digest
    common = ("--plan", str(plan_path), "--app", str(w01_runtime.app),
              "--model", str(w01_runtime.model), "--owner", owner)
    apply = ("write", "apply", *common, "--reviewed-digest", digest, "--apply")
    assert run(*apply)["classification"] == "applied"
    after = inspect(w01_runtime, db, tmp_path)
    assert after["source_absent"] is True
    assert after["card_payees"] == ["w09-survivor", "w09-unrelated"]
    for reference in seeded["references"]:
        assert reference["object_uri"] in after["survivor_references"][reference["relationship"]]
    assert run(*apply)["classification"] == "noop"
    assert run("write", "recover", *common)["classification"] == "noop"

    fuzzy_dir = tmp_path / "fuzzy"
    fuzzy_dir.mkdir()
    fuzzy_db, fuzzy_seeded = store(w01_runtime, fuzzy_dir, "--w09-fuzzy")
    fuzzy_owner = fuzzy_seeded["owner_uri"].rsplit("/p", 1)[1]
    review_map = tmp_path / "fuzzy-review.csv"
    fields = ("user_id", "similarity", "reason", "left_id", "left_name",
              "right_id", "right_name", "review_decision", "approved_canonical_id",
              "review_notes")
    with review_map.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"user_id": fuzzy_owner, "similarity": "0.9",
                         "reason": "similarity", "left_id": fuzzy_seeded["source"]["numeric_id"],
                         "left_name": fuzzy_seeded["source"]["name"],
                         "right_id": fuzzy_seeded["survivor"]["numeric_id"],
                         "right_name": fuzzy_seeded["survivor"]["name"],
                         "review_decision": "pending", "approved_canonical_id": "",
                         "review_notes": ""})

    def run_fuzzy(*arguments: str) -> dict:
        result = subprocess.run(
            [sandbox, "-p", profile, str(launcher), "--db", str(fuzzy_db), *arguments],
            cwd=tmp_path, env=environment, capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    fuzzy_plan = tmp_path / "fuzzy-plan.json"
    fuzzy_args = ("payee", "merge", "--kind", "fuzzy", "--source-gid", "w09-source",
                  "--survivor-gid", "w09-survivor", "--evidence-note", "Reviewed pair",
                  "--fuzzy-map", str(review_map), "--app", str(w01_runtime.app),
                  "--model", str(w01_runtime.model), "--owner", fuzzy_owner,
                  "--plan", str(fuzzy_plan))
    assert run_fuzzy(*fuzzy_args)["status"] == "skipped"
    assert not fuzzy_plan.exists()
    lines = review_map.read_text(encoding="utf-8").replace(",pending,,", ",approved,"
        + fuzzy_seeded["survivor"]["numeric_id"] + ",Same merchant")
    review_map.write_text(lines, encoding="utf-8")
    fuzzy_planned = run_fuzzy(*fuzzy_args)
    assert fuzzy_planned["status"] == "planned"
    fuzzy_common = ("--plan", str(fuzzy_plan), "--app", str(w01_runtime.app),
                    "--model", str(w01_runtime.model), "--owner", fuzzy_owner)
    assert run_fuzzy("write", "apply", *fuzzy_common, "--reviewed-digest",
                     fuzzy_planned["plan_digest"], "--apply")["classification"] == "applied"
    assert run_fuzzy("write", "recover", *fuzzy_common)["classification"] == "noop"
