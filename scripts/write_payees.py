#!/usr/bin/env python3
"""Build one reviewed W09 payee merge from a native reference inventory."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from merge_duplicate_payees import _spreadsheet_literal
from runtime_identity import RuntimeIdentityError, resolve_runtime_identity
from write_plan import PAYEE_MERGE_CAPABILITIES, PlanValidationError, validate_plan
from write_transactions import _write_plan
from writer_client import WriterClientError, resolve_writer


def _approval_from_map(path: Path, inventory: dict[str, Any]) -> dict[str, Any] | None:
    raw = path.read_bytes()
    with io.StringIO(raw.decode("utf-8-sig"), newline="") as source:
        reader = csv.DictReader(source)
        required = {
            "user_id", "similarity", "reason", "left_id", "left_name",
            "right_id", "right_name", "review_decision", "approved_canonical_id",
            "review_notes",
        }
        if reader.fieldnames is None or set(reader.fieldnames) != required:
            raise PlanValidationError("W09 fuzzy map has unknown or missing columns")
        rows = list(reader)
    source_id, survivor_id = inventory["source"]["numeric_id"], inventory["survivor"]["numeric_id"]
    owner_id = inventory["owner_uri"].rsplit("/p", 1)[1]
    matching = [row for row in rows if {row["left_id"], row["right_id"]} == {source_id, survivor_id}
                and row["user_id"] == owner_id]
    if len(matching) != 1:
        raise PlanValidationError("W09 fuzzy map must identify the exact pair once")
    row = matching[0]
    actual_names = {
        source_id: _spreadsheet_literal(inventory["source"]["name"]),
        survivor_id: _spreadsheet_literal(inventory["survivor"]["name"]),
    }
    if (actual_names.get(row["left_id"]) != row["left_name"]
            or actual_names.get(row["right_id"]) != row["right_name"]):
        raise PlanValidationError("W09 fuzzy map names differ from current payees")
    decision = row["review_decision"]
    if decision in {"pending", "rejected"}:
        return None
    if (decision != "approved" or row["approved_canonical_id"] != survivor_id
            or not row["review_notes"].strip()):
        raise PlanValidationError("W09 fuzzy map does not approve the chosen survivor")
    return {
        "user_id": int(owner_id),
        "left_id": row["left_id"],
        "left_name": inventory["source"]["name"] if row["left_id"] == source_id else inventory["survivor"]["name"],
        "right_id": row["right_id"],
        "right_name": inventory["source"]["name"] if row["right_id"] == source_id else inventory["survivor"]["name"],
        "review_decision": decision,
        "approved_canonical_id": survivor_id,
        "review_notes": row["review_notes"].strip(),
        "map_sha256": hashlib.sha256(raw).hexdigest(),
    }


def build_merge_plan(
    inventory: dict[str, Any], *, store_uuid: str, app_identity: dict[str, str],
    model_checksum: str, kind: str, evidence_note: str,
    approval: dict[str, Any] | None,
) -> dict[str, Any]:
    event = str(uuid.uuid4())
    return validate_plan({
        "contract_version": 2,
        "operation_schema_version": 1,
        "plan_id": f"w09-{event}",
        "profile_id": "moneywiz-2026-model-48",
        "model_checksum": model_checksum,
        "store_identity": {"store_uuid": store_uuid},
        "owner_uri": inventory["owner_uri"],
        "app_identity": app_identity,
        "capability": PAYEE_MERGE_CAPABILITIES[kind],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_event_id": event,
        "merge": {
            "operation_id": "merge-1",
            "kind": kind,
            "source": inventory["source"],
            "survivor": inventory["survivor"],
            "expected_references": inventory["references"],
            "evidence_note": evidence_note,
            "approval": approval,
        },
    })


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    merge = commands.add_parser("merge")
    merge.add_argument("--source-gid", required=True)
    merge.add_argument("--survivor-gid", required=True)
    merge.add_argument("--kind", choices=("exact", "fuzzy"), required=True)
    merge.add_argument("--evidence-note", required=True)
    merge.add_argument("--fuzzy-map", type=Path)
    merge.add_argument("--app", type=Path)
    merge.add_argument("--model", type=Path)
    merge.add_argument("--owner", type=int)
    merge.add_argument("--plan", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        if (args.kind == "fuzzy") != (args.fuzzy_map is not None):
            raise PlanValidationError("W09 fuzzy merge requires one reviewed --fuzzy-map")
        if not args.evidence_note.strip():
            raise PlanValidationError("W09 requires a nonblank evidence note")
        writer = resolve_writer(script_file=__file__)
        runtime = resolve_runtime_identity(
            args.db, owner_id=args.owner, app_path=args.app,
            model_path=args.model, model_checksum_host=writer,
        )
        completed = subprocess.run([
            str(writer), "--coredata-payee-inventory", "--store", str(runtime.store.path),
            "--model", str(runtime.model_path), "--source", args.source_gid,
            "--survivor", args.survivor_gid,
        ], capture_output=True, text=True, check=False)
        if completed.returncode:
            raise WriterClientError(completed.stderr.strip() or "W09 inventory failed")
        inventory = json.loads(completed.stdout)
        expected_owner = f"x-coredata://{runtime.store.uuid}/User/p{runtime.store.owner_local_id}"
        if inventory["owner_uri"] != expected_owner:
            raise PlanValidationError("W09 inventory owner differs from selected runtime")
        approval = _approval_from_map(args.fuzzy_map, inventory) if args.fuzzy_map else None
        if args.kind == "fuzzy" and approval is None:
            print(json.dumps({"status": "skipped", "reason": "pending or rejected review row"}))
            return 0
        kind = "merge_exact_payee" if args.kind == "exact" else "merge_approved_fuzzy_payee"
        plan = build_merge_plan(
            inventory, store_uuid=runtime.store.uuid,
            app_identity={"bundle_id": runtime.app.bundle_identifier,
                          "version": runtime.app.version, "path": str(runtime.app.path),
                          "model_path": str(runtime.model_path)},
            model_checksum=runtime.store.model_checksum, kind=kind,
            evidence_note=args.evidence_note.strip(), approval=approval,
        )
        _write_plan(args.plan, plan)
        print(json.dumps({"status": "planned", "plan": str(args.plan.resolve()),
                          "plan_digest": plan["plan_digest"]}))
        return 0
    except (PlanValidationError, WriterClientError, RuntimeIdentityError,
            OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
