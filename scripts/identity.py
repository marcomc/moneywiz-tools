"""Read-only CLI discovery of a bound MoneyWiz application/store/model tuple."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime_identity import RuntimeIdentityError, resolve_runtime_identity


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discover exact MoneyWiz runtime identity (read-only)"
    )
    parser.add_argument(
        "--db", type=Path, help="Explicit database; otherwise discover supported stores"
    )
    parser.add_argument("--app", type=Path, help="Explicit MoneyWiz application bundle")
    parser.add_argument("--model", type=Path, help="Explicit compiled model")
    parser.add_argument(
        "--owner", type=int, help="Store-local User ID when multiple owners exist"
    )
    args = parser.parse_args()
    try:
        identity = resolve_runtime_identity(
            args.db, owner_id=args.owner, app_path=args.app, model_path=args.model
        )
        print(json.dumps(identity.plan_binding(), indent=2))
        return 0
    except RuntimeIdentityError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
