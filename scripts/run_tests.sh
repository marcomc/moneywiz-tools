#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."

# Ensure venv with uv
if ! command -v uv >/dev/null 2>&1; then
  echo "Error: 'uv' not installed. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 127
fi

VENV_DIR="${REPO_ROOT}/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
  uv venv --python 3.11 "$VENV_DIR"
fi

# Install test dependencies if needed (pytest is used by API already)
uv pip install pytest --python "$VENV_DIR/bin/python"

export PYTHONPATH="${REPO_ROOT}/moneywiz-api/src${PYTHONPATH:+:${PYTHONPATH}}"

echo "Running API unit tests..."
"$VENV_DIR/bin/python" -m pytest -q moneywiz-api/tests/unit

echo "Running CLI tests..."
"$VENV_DIR/bin/python" -m pytest -q tests

echo "All tests passed."
