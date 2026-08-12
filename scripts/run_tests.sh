#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."

# Ensure venv with uv
if ! command -v uv >/dev/null 2>&1; then
  echo "Error: 'uv' not installed. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 127
fi

cd "${REPO_ROOT}"
uv sync --frozen
uv run --frozen pytest -q tests/cli
uv run --frozen python scripts/shell_examples_test.py

echo "All MoneyWiz Tools tests passed."
