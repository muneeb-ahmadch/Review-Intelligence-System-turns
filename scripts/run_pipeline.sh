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
"$PYTHON_BIN" pipeline/03_enrich_issues.py
"$PYTHON_BIN" pipeline/04_score_severity.py
"$PYTHON_BIN" pipeline/05_user_churn.py
"$PYTHON_BIN" pipeline/06_aggregates_daily.py
"$PYTHON_BIN" pipeline/07_aggregates_version.py
