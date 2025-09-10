#!/usr/bin/env bash

# Launch MoneyWiz CLI inside a uv-managed virtual environment.
# - Ensures a local .venv exists
# - Installs runtime dependencies via `uv pip install -r requirements.txt`
# - Runs the CLI with your DB path (overridable as first arg)
#
# Examples:
#   ./uv-run-moneywiz-cli.sh
#   ./uv-run-moneywiz-cli.sh --demo-dump --log-level DEBUG
#   ./uv-run-moneywiz-cli.sh /custom/path/ipadMoneyWiz.sqlite

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Default DB path (test database)
DEFAULT_DB_PATH="${SCRIPT_DIR}/tests/test_db.sqlite"

# Default DB path used unless overridden via global --db
DB_PATH="${DEFAULT_DB_PATH}"

# Use local uv cache dir to avoid permission issues
export UV_CACHE_DIR="${SCRIPT_DIR}/.uv-cache"
mkdir -p "$UV_CACHE_DIR"

# Require uv
if ! command -v uv >/dev/null 2>&1; then
  echo "Error: 'uv' is not installed." >&2
  echo "Install uv (see https://docs.astral.sh/uv/getting-started/), e.g.:" >&2
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 127
fi

# Create or reuse local venv
VENV_DIR="${SCRIPT_DIR}/.venv"
PY_REQ="3.11"
if [[ ! -d "$VENV_DIR" ]]; then
  uv venv --python "$PY_REQ" "$VENV_DIR"
else
  # Recreate venv if Python version is too old (< 3.11)
  if ! "$VENV_DIR/bin/python" - <<'PY'
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
PY
  then
    echo "Refreshing virtualenv with Python ${PY_REQ} (found older Python)."
    rm -rf "$VENV_DIR"
    uv venv --python "$PY_REQ" "$VENV_DIR"
  fi
fi

# Install runtime deps
if [[ -f "${SCRIPT_DIR}/requirements.txt" ]]; then
  uv pip install -r "${SCRIPT_DIR}/requirements.txt" --python "$VENV_DIR/bin/python"
fi

# PYTHONPATH to use local source tree directly
export PYTHONPATH="${SCRIPT_DIR}/moneywiz-api/src${PYTHONPATH:+:${PYTHONPATH}}"

usage() {
  cat <<USAGE
Usage: ./moneywiz.sh [--db PATH] <command> [options]

Commands:
  shell                              Launch interactive shell (moneywiz-cli)
  users                              List users
  accounts       [--user ID]         List accounts (optionally for user)
  categories     --user ID [--full-name]
                                      List categories for user
  payees         [--user ID]         List payees (optionally for user)
  tags           [--user ID]         List tags (optionally for user)
  transactions   --account ID [--limit N] [--until YYYY-MM-DD] [--with-categories] [--with-tags]
                                      List transactions for an account
  holdings       --account ID        List investment holdings for an account
  record         (--id ID | --gid GID)  View a record by id or gid
  stats          [--out DIR]         Write simple stats snapshots to files
  summary                            Show counts per manager
  sql-preview                        Preview/apply SQL changes (dry-run by default)
  schema         [--out-md PATH]     Generate Markdown schema doc (default: doc/DB-SCHEMA.md)
                 [--out-json PATH]   Generate JSON schema dump (default: doc/schema.json)

All subcommands accept --db PATH to override the default DB.
USAGE
}

# Parse optional global --db PATH (must come before subcommand)
GLOBAL_DB=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --db)
      if [[ -n "${2-}" ]]; then GLOBAL_DB="$2"; shift 2; else echo "--db requires a path" >&2; exit 2; fi ;;
    --help|-h)
      usage; exit 0 ;;
    --*)
      echo "Unknown global option: $1" >&2; usage; exit 2 ;;
    *)
      break ;;
  esac
done

SUBCMD="${1-}"
if [[ -z "$SUBCMD" || "$SUBCMD" == "-h" || "$SUBCMD" == "--help" ]]; then
  usage; exit 0
fi
shift || true

# Compose base python and db args for scripts
PY="$VENV_DIR/bin/python"
BASE_DB_ARG=( )
if [[ -n "$GLOBAL_DB" ]]; then BASE_DB_ARG=("--db" "$GLOBAL_DB"); else BASE_DB_ARG=("--db" "$DB_PATH"); fi

# Validate DB path for subcommands that need it (all except 'shell' when --help)
if [[ "$SUBCMD" != "shell" ]]; then
  DB_TO_USE="${GLOBAL_DB:-$DB_PATH}"
  if [[ ! -f "$DB_TO_USE" ]]; then
    echo "Error: Database file not found: $DB_TO_USE" >&2
    echo "- Override with: ./moneywiz.sh --db /path/to/ipadMoneyWiz.sqlite $SUBCMD ..." >&2
    exit 1
  fi
fi

case "$SUBCMD" in
  shell)
    exec "$PY" "${SCRIPT_DIR}/scripts/run_moneywiz_cli.py" "${GLOBAL_DB:-$DB_PATH}" "$@" ;;
  users)
    exec "$PY" "${SCRIPT_DIR}/scripts/users.py" "${BASE_DB_ARG[@]}" "$@" ;;
  accounts)
    exec "$PY" "${SCRIPT_DIR}/scripts/accounts.py" "${BASE_DB_ARG[@]}" "$@" ;;
  categories)
    exec "$PY" "${SCRIPT_DIR}/scripts/categories.py" "${BASE_DB_ARG[@]}" "$@" ;;
  payees)
    exec "$PY" "${SCRIPT_DIR}/scripts/payees.py" "${BASE_DB_ARG[@]}" "$@" ;;
  tags)
    exec "$PY" "${SCRIPT_DIR}/scripts/tags.py" "${BASE_DB_ARG[@]}" "$@" ;;
  transactions)
    exec "$PY" "${SCRIPT_DIR}/scripts/transactions.py" "${BASE_DB_ARG[@]}" "$@" ;;
  holdings)
    exec "$PY" "${SCRIPT_DIR}/scripts/holdings.py" "${BASE_DB_ARG[@]}" "$@" ;;
  record)
    exec "$PY" "${SCRIPT_DIR}/scripts/record.py" "${BASE_DB_ARG[@]}" "$@" ;;
  stats)
    exec "$PY" "${SCRIPT_DIR}/scripts/stats.py" "${BASE_DB_ARG[@]}" "$@" ;;
  summary)
    exec "$PY" "${SCRIPT_DIR}/scripts/summary.py" "${BASE_DB_ARG[@]}" "$@" ;;
  sql-preview)
    exec "$PY" "${SCRIPT_DIR}/scripts/sql_preview.py" "${BASE_DB_ARG[@]}" "$@" ;;
  schema)
    # Options: --out-md PATH, --out-json PATH
    OUT_MD="${SCRIPT_DIR}/doc/DB-SCHEMA.md"
    OUT_JSON="${SCRIPT_DIR}/doc/schema.json"
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --out-md)
          OUT_MD="$2"; shift 2 ;;
        --out-json)
          OUT_JSON="$2"; shift 2 ;;
        --help|-h)
          echo "Usage: ./moneywiz.sh schema [--out-md PATH] [--out-json PATH]"; exit 0 ;;
        *)
          echo "Unknown schema option: $1" >&2; exit 2 ;;
      esac
    done
    mkdir -p "$(dirname "$OUT_MD")" "$(dirname "$OUT_JSON")"
    DB_TO_USE="${GLOBAL_DB:-$DB_PATH}"
    "$PY" "${SCRIPT_DIR}/scripts/introspect_db.py" --db "$DB_TO_USE" --format md > "$OUT_MD"
    "$PY" "${SCRIPT_DIR}/scripts/introspect_db.py" --db "$DB_TO_USE" --format json > "$OUT_JSON"
    echo "Schema written to $OUT_MD and $OUT_JSON"
    ;;
  *)
    echo "Unknown command: $SUBCMD" >&2; usage; exit 2 ;;
esac
