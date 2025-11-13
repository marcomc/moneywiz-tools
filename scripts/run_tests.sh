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

run_pytest() {
  local label="$1"; shift
  echo "Running ${label} (${*})..."
  echo "-> $VENV_DIR/bin/python -m pytest -q $*"
  "$VENV_DIR/bin/python" -m pytest -q "$@"
}

run_pytest "API unit tests" moneywiz-api/tests/unit
run_pytest "API integration tests" moneywiz-api/tests/integration
run_pytest "CLI tests" tests/cli

echo "All tests passed."
