from __future__ import annotations

import json
import math
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from pipeline.db import get_connection
from pipeline.migrations import run_migrations

FAILURE_TERMS: tuple[str, ...] = (
    "failed",
    "error",
    "declined",
    "not working",
    "stuck",
    "crash",
    "can't",
    "cant",
    "unable",
)

CRITICAL_ISSUES: tuple[str, ...] = (
    "transaction failure",
    "login/auth issues",
)

HIGH_ISSUES: tuple[str, ...] = (
    "performance issues",
    "glitches/bugs",
)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _extract_labels(issues_json: str | None) -> list[str]:
    if not issues_json:
        return []

    try:
        payload = json.loads(issues_json)
    except (json.JSONDecodeError, TypeError):
        return []

    labels: list[str] = []
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                label = item.get("label")
                if isinstance(label, str) and label.strip():
                    labels.append(label.strip().lower())
            elif isinstance(item, str) and item.strip():
                labels.append(item.strip().lower())
    elif isinstance(payload, dict):
        label = payload.get("label")
        if isinstance(label, str) and label.strip():
            labels.append(label.strip().lower())

    return labels


def _sentiment_component(sentiment_label: str | None) -> float:
    if sentiment_label == "negative":
        return 1.0
    if sentiment_label == "neutral":
        return 0.4
    if sentiment_label == "positive":
        return 0.1
    return 0.4


def _failure_component(content: str | None) -> float:
    txt = (content or "").lower()
    return 1.0 if any(term in txt for term in FAILURE_TERMS) else 0.0


def _critical_issue_component(issues_json: str | None) -> float:
    labels = _extract_labels(issues_json)
    if any(label in CRITICAL_ISSUES for label in labels):
        return 1.0
    if any(label in HIGH_ISSUES for label in labels):
        return 0.5
    return 0.3


def _thumbs_component(thumbs_up: int | None) -> float:
    value = max(0, int(thumbs_up or 0))
    return min(1.0, math.log(1 + value) / math.log(1 + 50))


def _severity_band(score: float) -> str:
    if score >= 0.80:
        return "critical"
    if score >= 0.60:
        return "high"
    if score >= 0.30:
        return "med"
    return "low"


def _compute_severity(
    score: int | None,
    sentiment_label: str | None,
    content: str | None,
    thumbs_up: int | None,
    issues_json: str | None,
) -> tuple[float, str]:
    star_score = max(1, min(5, int(score))) if score is not None else 3

    r = (5 - star_score) / 4
    s = _sentiment_component(sentiment_label)
    f = _failure_component(content)
    c = _critical_issue_component(issues_json)
    t = _thumbs_component(thumbs_up)

    severity = _clamp(0.35 * r + 0.25 * s + 0.15 * f + 0.15 * c + 0.10 * t, 0.0, 1.0)
    return severity, _severity_band(severity)


def main() -> None:
    run_migrations()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                r.review_id,
                r.content,
                r.score,
                r.thumbs_up,
                e.sentiment_label,
                e.issues_json
            FROM reviews_raw r
            JOIN reviews_enriched e ON e.review_id = r.review_id
            """
        ).fetchall()

        updates: list[tuple[float, str, str]] = []
        for review_id, content, score, thumbs_up, sentiment_label, issues_json in rows:
            severity, band = _compute_severity(score, sentiment_label, content, thumbs_up, issues_json)
            updates.append((severity, band, review_id))

        if updates:
            conn.executemany(
                """
                UPDATE reviews_enriched
                SET
                    severity_score = ?,
                    severity_band = ?,
                    processed_at = CURRENT_TIMESTAMP
                WHERE review_id = ?
                """,
                updates,
            )

        summary = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                AVG(severity_score) AS avg_severity,
                SUM(CASE WHEN severity_band = 'critical' THEN 1 ELSE 0 END) AS critical_rows
            FROM reviews_enriched
            """
        ).fetchone()

    print(
        "[04_score_severity] completed: "
        f"rows={summary[0]}, avg_severity={summary[1]:.4f}, critical_rows={summary[2]}"
    )


if __name__ == "__main__":
    main()
