from __future__ import annotations

from datetime import date, datetime
from typing import Any

import duckdb

from app.config import DUCKDB_PATH


def _to_date_string(value: str | date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _build_excerpt(content: str | None, issue_label: str | None, max_chars: int = 180) -> str:
    text = (content or "").strip().replace("\n", " ")
    if not text:
        return ""

    if len(text) <= max_chars:
        return text

    # Try to center the excerpt around a keyword from the issue label.
    lowered = text.lower()
    keywords = []
    if issue_label:
        keywords = [token.lower() for token in issue_label.split() if len(token) >= 4]

    for keyword in keywords:
        idx = lowered.find(keyword)
        if idx != -1:
            half = max_chars // 2
            start = max(0, idx - half)
            end = min(len(text), start + max_chars)
            snippet = text[start:end].strip()
            if start > 0:
                snippet = "..." + snippet
            if end < len(text):
                snippet = snippet + "..."
            return snippet

    return text[:max_chars].rstrip() + "..."


def get_evidence_quotes(
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    issue_label: str | None = None,
    version: str | None = None,
    category: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return top evidence quotes from reviews using optional drilldown filters."""
    start = _to_date_string(start_date)
    end = _to_date_string(end_date)
    safe_limit = max(1, min(int(limit), 50))

    where_clauses = ["1=1"]
    params: list[Any] = []

    if start:
        where_clauses.append("DATE(r.at_ts) >= ?")
        params.append(start)
    if end:
        where_clauses.append("DATE(r.at_ts) <= ?")
        params.append(end)
    if version:
        where_clauses.append("r.app_version = ?")
        params.append(version)
    if category:
        where_clauses.append("COALESCE(e.category_taxonomy, 'Other') = ?")
        params.append(category)
    if issue_label:
        where_clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM json_each(COALESCE(e.issues_json, '[]')) je
                WHERE LOWER(CAST(je.value ->> 'label' AS VARCHAR)) = LOWER(?)
            )
            """
        )
        params.append(issue_label)

    query = f"""
        SELECT
            r.review_id,
            DATE(r.at_ts) AS day,
            r.content,
            r.score,
            r.thumbs_up,
            r.app_version,
            COALESCE(e.category_taxonomy, 'Other') AS category_taxonomy,
            COALESCE(e.sentiment_label, 'unknown') AS sentiment_label,
            COALESCE(e.severity_score, 0.0) AS severity_score
        FROM reviews_raw r
        JOIN reviews_enriched e USING (review_id)
        WHERE {' AND '.join(where_clauses)}
        ORDER BY
            COALESCE(e.severity_score, 0.0) DESC,
            COALESCE(r.thumbs_up, 0) DESC,
            r.at_ts DESC
        LIMIT ?
    """

    params.append(safe_limit)

    with duckdb.connect(str(DUCKDB_PATH), read_only=True) as conn:
        rows = conn.execute(query, params).fetchall()

    evidence: list[dict[str, Any]] = []
    for review_id, day, content, score, thumbs_up, app_version, cat, sentiment, severity in rows:
        evidence.append(
            {
                "review_id": review_id,
                "day": str(day),
                "score": score,
                "thumbs_up": thumbs_up,
                "app_version": app_version,
                "category_taxonomy": cat,
                "sentiment_label": sentiment,
                "severity_score": round(float(severity or 0.0), 3),
                "quote": _build_excerpt(content, issue_label),
            }
        )

    return evidence
