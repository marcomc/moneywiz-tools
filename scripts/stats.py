#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

from moneywiz_api.moneywiz_api import MoneywizApi
from moneywiz_api.cli.helpers import ShellHelper


def default_db() -> Path:
    return Path(__file__).resolve().parents[1] / "tests/test_db.sqlite"


def main() -> int:
    ap = argparse.ArgumentParser(description="Write simple stats snapshots to files")
    ap.add_argument("--db", type=Path, default=default_db(), help="Path to MoneyWiz sqlite DB")
    ap.add_argument("--out", type=Path, default=Path("data/stats"), help="Output directory")
    args = ap.parse_args()

    api = MoneywizApi(args.db)
    helper = ShellHelper(api)
    helper.write_stats_data_files(args.out)
    print(f"Wrote stats files under {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
