#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"

if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${ROOT_DIR}/.venv/Scripts/python.exe" ]]; then
    PYTHON_BIN="${ROOT_DIR}/.venv/Scripts/python.exe"
  elif [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
  else
    PYTHON_BIN="python"
  fi
fi

echo "Using Python: ${PYTHON_BIN}"
"${PYTHON_BIN}" -m pip install --upgrade build
"${PYTHON_BIN}" -m build

echo "Built artifacts in: ${ROOT_DIR}/dist"
