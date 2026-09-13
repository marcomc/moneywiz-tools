"""Exercise the actual Python/native JSON boundary without any financial store."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from test_transaction_create import request
from test_write_plan import plan
from write_journal import store_lock
from write_plan import validate_plan
from write_transactions import build_plan


@pytest.fixture(scope="module")
def native_plan_validator(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = Path(__file__).resolve().parents[2]
    directory = tmp_path_factory.mktemp("native-plan-validator")
    main = directory / "main.swift"
    main.write_text("""import Foundation
@main struct Validate {
    static func main() {
        do {
            if CommandLine.arguments.count == 3 && CommandLine.arguments[1] == "--lock" {
                try withWriterLock(storeURL: URL(fileURLWithPath: CommandLine.arguments[2])) {
                    print("locked")
                }
                return
            }
            let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
            let raw = try JSONSerialization.jsonObject(with: data) as! [String: Any]
            let plan = try JSONDecoder().decode(WriterPlanV2.self, from: data)
            try validateWriterPlanV2(plan, rawPlan: raw)
            print(try canonicalV2Digest(raw))
        } catch {
            FileHandle.standardError.write(Data(error.localizedDescription.utf8))
            exit(2)
        }
    }
}
""")
    executable = directory / "validator"
    compiled = subprocess.run(
        [
            "swiftc",
            "-parse-as-library",
            "-D",
            "MONEYWIZ_TOOLS_TESTING",
            str(root / "scripts/moneywiz_tools_host.swift"),
            str(main),
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    return executable


def test_python_plan_validates_natively_with_identical_unicode_digest(
    native_plan_validator: Path, tmp_path: Path
) -> None:
    payload = plan()
    payload["profile_id"] = "moneywiz-2026-model-48"
    payload["model_checksum"] = "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ="
    payload["source_evidence_refs"] = ["synthetic://café/👩/\tline"]
    validated = validate_plan(payload)
    source = tmp_path / "plan.json"
    source.write_text(json.dumps(validated))
    completed = subprocess.run(
        [str(native_plan_validator), str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == validated["plan_digest"]


def test_native_validator_rejects_changed_reviewed_fields(
    native_plan_validator: Path, tmp_path: Path
) -> None:
    payload = plan()
    payload["profile_id"] = "moneywiz-2026-model-48"
    payload["model_checksum"] = "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ="
    validated = validate_plan(payload)
    validated["operations"][0]["target_payee_gid"] = "unreviewed-target"
    source = tmp_path / "plan.json"
    source.write_text(json.dumps(validated))
    completed = subprocess.run(
        [str(native_plan_validator), str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2


def test_python_w01_creation_plan_validates_natively(
    native_plan_validator: Path, tmp_path: Path
) -> None:
    validated = build_plan(request())
    source = tmp_path / "create-plan.json"
    source.write_text(json.dumps(validated))
    completed = subprocess.run(
        [str(native_plan_validator), str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == validated["plan_digest"]


def test_native_and_python_share_the_same_private_store_lock(
    native_plan_validator: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "isolated-home"))
    database = tmp_path / "synthetic.sqlite"
    database.touch()
    with store_lock(database) as descriptor:
        competing = subprocess.run(
            [str(native_plan_validator), "--lock", str(database)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert competing.returncode == 2
        inherited = subprocess.run(
            [str(native_plan_validator), "--lock", str(database)],
            env={**os.environ, "MONEYWIZ_WRITER_LOCK_FD": str(descriptor)},
            pass_fds=(descriptor,),
            capture_output=True,
            text=True,
            check=False,
        )
        assert inherited.returncode == 0, inherited.stderr
        assert inherited.stdout.strip() == "locked"
