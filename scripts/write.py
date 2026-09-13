#!/usr/bin/env python3
"""Review versioned plans and manage private writer recovery evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime_identity import RuntimeIdentityError, resolve_runtime_identity
from write_journal import JournalError, JournalPaths, JournalStore
from write_plan import PlanValidationError, load_plan
from writer_client import WriterClient, WriterClientError, resolve_writer


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, help="Explicit store; otherwise use runtime discovery"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "apply", "recover"):
        command = commands.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        if name != "validate":
            command.add_argument("--app", type=Path)
            command.add_argument("--model", type=Path)
            command.add_argument("--owner", type=int)
        if name == "apply":
            command.add_argument(
                "--reviewed-digest", help="Digest of the exact reviewed plan"
            )
            command.add_argument(
                "--apply", action="store_true", help="Explicitly permit mutation"
            )
    commands.add_parser(
        "locations", help="Effective private paths and retention policy"
    )
    commands.add_parser(
        "journal", help="List recovery entries and their outcome states"
    )
    cleanup = commands.add_parser(
        "cleanup", help="List eligible journal evidence; preserve unresolved work"
    )
    cleanup.add_argument(
        "--apply", action="store_true", help="Delete currently eligible evidence"
    )
    return parser


def _client(args: argparse.Namespace, plan: dict) -> WriterClient:
    writer = resolve_writer(script_file=__file__)
    identity = resolve_runtime_identity(
        args.db,
        owner_id=args.owner,
        app_path=args.app,
        model_path=args.model,
        model_checksum_host=writer,
    )
    app = plan["app_identity"]
    owner_uri = (
        f"x-coredata://{identity.store.uuid}/User/p{identity.store.owner_local_id}"
    )
    if (
        plan["store_identity"]["store_uuid"] != identity.store.uuid
        or plan["owner_uri"] != owner_uri
        or plan["model_checksum"] != identity.store.model_checksum
        or app["bundle_id"] != identity.app.bundle_identifier
        or app["version"] != identity.app.version
        or Path(app["path"]).resolve() != identity.app.path.resolve()
        or Path(app["model_path"]).resolve() != identity.model_path.resolve()
    ):
        raise WriterClientError(
            "selected runtime does not match the reviewed plan identity"
        )
    return WriterClient(
        writer=writer, model=identity.model_path, store=identity.store.path
    )


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        if args.command in {"validate", "apply", "recover"}:
            plan = load_plan(str(args.plan))
            if args.command == "validate" or (
                args.command == "apply" and not args.apply
            ):
                result = {
                    "status": "planned",
                    "plan_digest": plan["plan_digest"],
                    "plan": plan,
                }
            else:
                if (
                    args.command == "apply"
                    and args.reviewed_digest != plan["plan_digest"]
                ):
                    raise PlanValidationError(
                        "--apply requires the exact --reviewed-digest"
                    )
                client = _client(args, plan)
                journal = JournalStore(JournalPaths.from_environ())
                result = (
                    client.apply(plan, args.reviewed_digest, journal)
                    if args.command == "apply"
                    else client.recover(plan, journal)
                )
        else:
            paths = JournalPaths.from_environ()
            if args.command == "locations":
                result = paths.locations()
            elif args.command == "journal":
                result = {"entries": JournalStore(paths, create=False).list_entries()}
            else:
                result = JournalStore(paths, create=args.apply).cleanup(
                    apply=args.apply
                )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 3 if result.get("classification") == "unknown" else 0
    except (
        PlanValidationError,
        WriterClientError,
        JournalError,
        RuntimeIdentityError,
        OSError,
    ) as exc:
        print(
            json.dumps(
                {"status": "error", "error": type(exc).__name__, "message": str(exc)}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
