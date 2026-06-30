"""Hugging Face Spaces entrypoint.

Spaces runs this file. The committed DuckDB ships with the repo, so the dashboard
and the cached insight reports work immediately — no pipeline run, no Ollama, no
API key required. If you set ANTHROPIC_API_KEY as a Space secret, the "Generate"
buttons will produce fresh insights with Claude; otherwise they serve the cached
sample outputs.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.gradio_app import build_app
from app.ui.theme import build_theme, load_css

demo = build_app()

if __name__ == "__main__":
    css_path = Path(__file__).resolve().parent / "app" / "ui" / "styles.css"
    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", "7860")),
        theme=build_theme(),
        css=load_css(css_path),
    )
