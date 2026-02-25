from __future__ import annotations

from pathlib import Path

import gradio as gr

DESIGN_TOKENS = {
    "bg": "#f6f8fb",
    "surface": "#ffffff",
    "muted": "#6b7280",
    "text": "#0f172a",
    "primary": "#2563eb",
    "border": "#dbe3ef",
    "shadow": "0 10px 30px rgba(15, 23, 42, 0.08)",
    "radius": "14px",
}

CSS_VARIABLES = f"""
:root {{
  --bg: {DESIGN_TOKENS['bg']};
  --surface: {DESIGN_TOKENS['surface']};
  --muted: {DESIGN_TOKENS['muted']};
  --text: {DESIGN_TOKENS['text']};
  --primary: {DESIGN_TOKENS['primary']};
  --border: {DESIGN_TOKENS['border']};
  --shadow: {DESIGN_TOKENS['shadow']};
  --radius: {DESIGN_TOKENS['radius']};
}}
"""


def build_theme() -> gr.themes.ThemeClass:
    return gr.themes.Soft(
        primary_hue="blue",
        secondary_hue="slate",
        neutral_hue="slate",
        radius_size="lg",
        spacing_size="md",
        text_size="md",
    ).set(
        body_background_fill=DESIGN_TOKENS["bg"],
        block_background_fill=DESIGN_TOKENS["surface"],
        block_border_color=DESIGN_TOKENS["border"],
        block_shadow=DESIGN_TOKENS["shadow"],
        body_text_color=DESIGN_TOKENS["text"],
        body_text_color_subdued=DESIGN_TOKENS["muted"],
        button_primary_background_fill=DESIGN_TOKENS["primary"],
        button_primary_border_color=DESIGN_TOKENS["primary"],
        button_primary_text_color="#ffffff",
    )


def load_css(styles_path: Path) -> str:
    css = CSS_VARIABLES
    if styles_path.exists():
        css = f"{css}\n{styles_path.read_text(encoding='utf-8')}"
    return css
