#!/usr/bin/env bash
set -euo pipefail

: "${GRADIO_SERVER_PORT:=7861}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

"$PYTHON_BIN" -m app.gradio_app
