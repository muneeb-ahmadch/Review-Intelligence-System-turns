from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

from app.config import ROOT_DIR
from llm.ollama_client import call_ollama


Validator = Callable[[dict[str, Any]], None]


def call_json_with_retry(
    model: str,
    system: str,
    user: str,
    schema_validator: Validator,
    max_retries: int = 2,
) -> dict[str, Any]:
    env_retries = os.getenv("OLLAMA_JSON_MAX_RETRIES")
    if env_retries:
        max_retries = max(1, int(env_retries))

    last_error: str | None = None
    prompt_user = user

    for attempt in range(max_retries):
        text = call_ollama(model=model, system=system, user=prompt_user)
        try:
            payload = json.loads(text)
            schema_validator(payload)
            return payload
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            if attempt == 0:
                prompt_user = (
                    "Return ONLY valid JSON. Fix the malformed JSON below.\n\n"
                    f"Malformed JSON:\n{text}\n\n"
                    f"Validation/parse error:\n{last_error}"
                )
            else:
                prompt_user = (
                    f"{user}\n\nRETRY: Return ONLY valid JSON. "
                    f"Previous error: {last_error}"
                )
            time.sleep(0.2)

    raise ValueError(f"Invalid JSON after retries: {last_error}")


def load_json_schema(schema_path: str | Path) -> dict[str, Any]:
    path = Path(schema_path)
    if not path.is_absolute():
        path = ROOT_DIR / path
    return json.loads(path.read_text(encoding="utf-8"))


def build_jsonschema_validator(schema: dict[str, Any]) -> Validator:
    validator = Draft202012Validator(schema)

    def _validate(payload: dict[str, Any]) -> None:
        validator.validate(payload)

    return _validate
