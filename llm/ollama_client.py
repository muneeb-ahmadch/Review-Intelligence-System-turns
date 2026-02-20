from __future__ import annotations

from typing import Any

import requests


def call_ollama(model: str, system: str, user: str, temperature: float = 0.2) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": temperature},
    }
    response = requests.post(
        "http://localhost:11434/api/chat",
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]
