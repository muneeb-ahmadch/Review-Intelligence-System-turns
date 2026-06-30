"""LLM provider selection.

The insight layer is provider-agnostic. We pick a backend at call time from the
environment, in this order:

1. Anthropic Claude  -- if ANTHROPIC_API_KEY is set (best models, works on a
   hosted demo where there is no local GPU). Uses the official `anthropic` SDK.
2. Ollama / Llama 3.2 -- if a local Ollama server is reachable. This is what the
   committed sample insight cache was generated with.
3. None               -- no live LLM available. Callers fall back to the cached
   sample reports in DuckDB, or to the deterministic grounded fallback.

Keeping this legible matters more than cleverness: every insight is built from a
grounded input payload (KPI counts + top issues + real evidence quotes), the
prompts live as plain files under llm/prompts/, and the output is validated
against a JSON schema before it is ever shown. See llm/grounding.py for the
post-generation guardrails.
"""

from __future__ import annotations

import os
from typing import Optional

import requests

from llm.ollama_client import (
    DEFAULT_MODEL as OLLAMA_MODEL,
    OLLAMA_BASE_URL,
    call_ollama,
)


class ProviderUnavailable(RuntimeError):
    """Raised when no live LLM backend is configured or reachable."""


ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
_ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "2000"))


def _anthropic_available() -> bool:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _ollama_available() -> bool:
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags", timeout=2)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def active_provider() -> tuple[Optional[str], Optional[str]]:
    """Return (provider_name, model_id) for the backend that would be used now."""
    if _anthropic_available():
        return "anthropic", ANTHROPIC_MODEL
    if _ollama_available():
        return "ollama", OLLAMA_MODEL
    return None, None


def _generate_anthropic(system: str, user: str) -> str:
    import anthropic

    client = anthropic.Anthropic()
    # JSON-only output is enforced by the system prompt + downstream schema
    # validation/retry, mirroring the Ollama path so both backends behave the
    # same. claude-opus-4-8 uses adaptive thinking by default; no thinking config
    # is required.
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=_ANTHROPIC_MAX_TOKENS,
        system=system + "\n\nReturn ONLY a single valid JSON object. No prose, no markdown.",
        messages=[{"role": "user", "content": user}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def generate(system: str, user: str) -> str:
    """Generate raw model text from the active provider, or raise."""
    provider, _ = active_provider()
    if provider == "anthropic":
        return _generate_anthropic(system, user)
    if provider == "ollama":
        return call_ollama(model=OLLAMA_MODEL, system=system, user=user)
    raise ProviderUnavailable(
        "No live LLM backend available (set ANTHROPIC_API_KEY or run Ollama). "
        "Serving cached sample insights instead."
    )
