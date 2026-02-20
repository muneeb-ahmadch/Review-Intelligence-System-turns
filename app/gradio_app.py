from __future__ import annotations

import os
import sys
from pathlib import Path

import gradio as gr

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.config import DUCKDB_PATH


def build_app() -> gr.Blocks:
    db_status = "ready" if DUCKDB_PATH.exists() else "not ready"

    with gr.Blocks(title="Review Intelligence MVP") as demo:
        gr.Markdown("# Review Intelligence MVP")
        gr.Markdown("Hello. Dashboard wiring is in progress.")
        gr.Markdown(f"DuckDB status: **{db_status}** (`{DUCKDB_PATH}`)")

    return demo


def main() -> None:
    app = build_app()
    server_port = int(os.getenv("GRADIO_SERVER_PORT", "7861"))
    app.launch(server_name="127.0.0.1", server_port=server_port)


if __name__ == "__main__":
    main()
