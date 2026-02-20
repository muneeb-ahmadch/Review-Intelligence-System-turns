#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

"$PYTHON_BIN" pipeline/migrations.py
"$PYTHON_BIN" pipeline/00_ingest.py
"$PYTHON_BIN" pipeline/01_normalize.py
"$PYTHON_BIN" pipeline/02_enrich_sentiment.py
"$PYTHON_BIN" pipeline/04_score_severity.py
