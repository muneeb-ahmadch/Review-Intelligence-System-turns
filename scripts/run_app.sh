#!/usr/bin/env bash
set -euo pipefail

: "${GRADIO_SERVER_PORT:=7861}"
python3 -m app.gradio_app
