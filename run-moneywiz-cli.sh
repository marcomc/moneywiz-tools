#!/usr/bin/env bash

# Simple launcher for the MoneyWiz interactive shell, using the local source tree.
# Usage examples:
#   bash run-moneywiz-cli.sh                      # start with defaults
#   bash run-moneywiz-cli.sh --demo-dump          # print demo tables first
#   bash run-moneywiz-cli.sh --log-level DEBUG    # verbose logging

set -euo pipefail

# Default DB path (Setapp edition)
DEFAULT_DB_PATH="/Users/mmassari/Library/Containers/com.moneywiz.personalfinance-setapp/Data/Documents/.AppData/ipadMoneyWiz.sqlite"

# Allow first positional arg to override DB path if it looks like a file
DB_PATH="${DEFAULT_DB_PATH}"
if [[ "${1-}" != "" && "${1-}" != -* ]]; then
  # If user passes a first positional arg, use it as DB path
  DB_PATH="$1"
  shift
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Ensure the local package source is importable without installation
export PYTHONPATH="${SCRIPT_DIR}/moneywiz-api/src${PYTHONPATH:+:${PYTHONPATH}}"

# Choose a Python interpreter (prefer python3)
if command -v python3 >/dev/null 2>&1; then
  PYBIN=python3
elif command -v python >/dev/null 2>&1; then
  PYBIN=python
else
  echo "Error: No Python interpreter found. Please install Python 3 and ensure 'python3' or 'python' is on PATH." >&2
  exit 127
fi

# If help is requested, don't require the path to exist (Click handles help early)
for arg in "$@"; do
  if [[ "$arg" == "-h" || "$arg" == "--help" ]]; then
    exec "$PYBIN" "$SCRIPT_DIR/scripts/run_moneywiz_cli.py" --help
  fi
done

# Validate DB path exists and is readable
if [[ ! -f "$DB_PATH" ]]; then
  echo "Error: Database file not found: $DB_PATH" >&2
  echo "- Pass a custom path: ./run-moneywiz-cli.sh /path/to/ipadMoneyWiz.sqlite" >&2
  echo "- Default used: $DEFAULT_DB_PATH" >&2
  exit 1
fi

# Launch the CLI with pytest shim, forwarding args
exec "$PYBIN" "$SCRIPT_DIR/scripts/run_moneywiz_cli.py" "$DB_PATH" "$@"
