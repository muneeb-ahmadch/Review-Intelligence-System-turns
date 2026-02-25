from __future__ import annotations

import os
from typing import Any

import requests


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
DEFAULT_CONNECT_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_CONNECT_TIMEOUT_SECONDS", "10"))
DEFAULT_READ_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_READ_TIMEOUT_SECONDS", "240"))
DEFAULT_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "420"))
DEFAULT_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.0"))


def call_ollama(
    model: str = DEFAULT_MODEL,
    system: str = "",
    user: str = "",
    temperature: float = DEFAULT_TEMPERATURE,
    connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    read_timeout_seconds: int = DEFAULT_READ_TIMEOUT_SECONDS,
    num_predict: int = DEFAULT_NUM_PREDICT,
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
        },
    }
    response = requests.post(
        f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat",
        json=payload,
        timeout=(connect_timeout_seconds, read_timeout_seconds),
    )
    response.raise_for_status()

    body = response.json()
    content = body.get("message", {}).get("content")
    if not isinstance(content, str):
        raise ValueError(f"Ollama response missing message.content: {body}")
    return content
