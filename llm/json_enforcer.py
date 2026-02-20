from __future__ import annotations

import json
import time
from typing import Any, Callable

from llm.ollama_client import call_ollama


Validator = Callable[[dict[str, Any]], None]


def call_json_with_retry(
    model: str,
    system: str,
    user: str,
    schema_validator: Validator,
    max_retries: int = 3,
) -> dict[str, Any]:
    last_error: str | None = None
    prompt_user = user

    for _ in range(max_retries):
        text = call_ollama(model=model, system=system, user=prompt_user)
        try:
            payload = json.loads(text)
            schema_validator(payload)
            return payload
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            prompt_user = (
                f"{user}\n\nRETRY: Return ONLY valid JSON. "
                f"Previous error: {last_error}"
            )
            time.sleep(0.2)

    raise ValueError(f"Invalid JSON after retries: {last_error}")
