"""Step 09 — materialise and cache the headline LLM insights.

Generates the Weekly Executive Brief and Sprint Backlog for the default scope
(the full data range) and caches them in `insight_reports`. This means a fresh
clone — or a hosted demo with no API key and no Ollama — still shows real,
grounded insight outputs (served from the cache) without anyone clicking
"Generate".

Provider precedence is handled in llm/provider.py: Anthropic Claude if
ANTHROPIC_API_KEY is set, else local Ollama, else the deterministic grounded
fallback. Whatever ran, the output is schema-validated and quote-grounded before
it is cached.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.services.insights_service import generate_sprint_backlog, generate_weekly_exec_brief
from llm.provider import active_provider
from pipeline.db import get_connection
from pipeline.migrations import run_migrations


def main() -> None:
    run_migrations()

    provider, model = active_provider()
    if provider:
        print(f"[09_insight_materialization] live provider: {provider} ({model})")
    else:
        print("[09_insight_materialization] no live LLM; using deterministic grounded fallback")

    # Clear stale cache so the committed cache matches the current data + code.
    with get_connection() as conn:
        conn.execute("DELETE FROM insight_reports")

    # Empty scope -> normalised to the full data range default.
    brief = generate_weekly_exec_brief({})
    print(f"[09_insight_materialization] cached weekly_exec_brief ({len(brief.get('drivers', []))} drivers)")

    backlog = generate_sprint_backlog({})
    print(f"[09_insight_materialization] cached sprint_backlog ({len(backlog.get('tickets', []))} tickets)")


if __name__ == "__main__":
    main()
