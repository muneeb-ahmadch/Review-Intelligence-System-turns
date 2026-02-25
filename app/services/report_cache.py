from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from pipeline.db import get_connection


ReportGenerator = Callable[[], dict[str, Any]]


def _ensure_insight_reports_table() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS insight_reports (
                report_id VARCHAR PRIMARY KEY,
                report_type VARCHAR,
                scope_json VARCHAR,
                content_json VARCHAR,
                created_at TIMESTAMP,
                model VARCHAR,
                hash_key VARCHAR UNIQUE
            )
            """
        )


def normalize_scope_json(scope: dict[str, Any]) -> str:
    return json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_hash_key(report_type: str, scope: dict[str, Any]) -> str:
    normalized_scope = normalize_scope_json(scope)
    key_source = f"{report_type}{normalized_scope}"
    return hashlib.sha256(key_source.encode("utf-8")).hexdigest()


def _get_cached_report(hash_key: str) -> dict[str, Any] | None:
    with get_connection(read_only=True) as conn:
        row = conn.execute(
            """
            SELECT content_json
            FROM insight_reports
            WHERE hash_key = ?
            """,
            [hash_key],
        ).fetchone()
    if not row:
        return None
    return json.loads(row[0])


def _insert_report(
    report_type: str,
    scope: dict[str, Any],
    content: dict[str, Any],
    model: str,
    hash_key: str,
) -> None:
    report_id = str(uuid.uuid4())
    created_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    normalized_scope = normalize_scope_json(scope)
    content_json = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO insight_reports (
                report_id,
                report_type,
                scope_json,
                content_json,
                created_at,
                model,
                hash_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [report_id, report_type, normalized_scope, content_json, created_at, model, hash_key],
        )


def get_or_create_report(
    report_type: str,
    scope: dict[str, Any],
    model: str,
    generator: ReportGenerator,
) -> dict[str, Any]:
    _ensure_insight_reports_table()
    hash_key = compute_hash_key(report_type=report_type, scope=scope)
    cached = _get_cached_report(hash_key)
    if cached is not None:
        return cached

    content = generator()

    try:
        _insert_report(report_type=report_type, scope=scope, content=content, model=model, hash_key=hash_key)
    except Exception:  # noqa: BLE001
        # Safe in race conditions: another insert may have won the unique hash key.
        cached_after_race = _get_cached_report(hash_key)
        if cached_after_race is not None:
            return cached_after_race
        raise

    return content
