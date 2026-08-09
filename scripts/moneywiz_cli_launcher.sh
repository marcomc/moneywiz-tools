#!/usr/bin/env bash

set -euo pipefail

resolve_script_path() {
  local source="$1"
  local directory=""
  local target=""
  while [[ -h "${source}" ]]; do
    directory="$(cd -P "$(dirname "${source}")" && pwd)"
    target="$(/usr/bin/readlink "${source}")"
    if [[ "${target}" == /* ]]; then
      source="${target}"
    else
      source="${directory}/${target}"
    fi
  done
  printf '%s' "${source}"
}

SOURCE_PATH="$(resolve_script_path "${BASH_SOURCE[0]}")"
BIN_DIR="$(cd -P "$(dirname "${SOURCE_PATH}")" && pwd)"
RUNTIME_DIR="$(cd -P "${BIN_DIR}/.." && pwd)"
PY="${RUNTIME_DIR}/python/venv/bin/python"

if [[ ! -x "${PY}" ]]; then
  echo "error: bundled Python runtime is incomplete at ${PY}" >&2
  exit 1
fi

export PYTHONPATH="${RUNTIME_DIR}/moneywiz-api/src${PYTHONPATH:+:${PYTHONPATH}}"
exec "${PY}" -m moneywiz_api.cli.cli "$@"
