from __future__ import annotations

from datetime import date, datetime
from typing import Any

import duckdb
import pandas as pd

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


def get_filter_options() -> dict[str, Any]:
    with duckdb.connect(str(DUCKDB_PATH), read_only=True) as conn:
        min_day, max_day = conn.execute(
            "SELECT MIN(DATE(at_ts)), MAX(DATE(at_ts)) FROM reviews_raw"
        ).fetchone()

        categories = [
            row[0]
            for row in conn.execute(
                """
                SELECT DISTINCT COALESCE(category_taxonomy, 'Other') AS category_taxonomy
                FROM reviews_enriched
                ORDER BY 1
                """
            ).fetchall()
        ]

        versions = [
            row[0]
            for row in conn.execute(
                """
                SELECT app_version
                FROM version_aggregates
                ORDER BY last_seen_day DESC, total_reviews DESC, app_version
                """
            ).fetchall()
            if row[0]
        ]

        issue_labels = [
            row[0]
            for row in conn.execute(
                """
                SELECT DISTINCT CAST(je.value ->> 'label' AS VARCHAR) AS issue_label
                FROM reviews_enriched e,
                     LATERAL json_each(COALESCE(e.issues_json, '[]')) AS je
                WHERE CAST(je.value ->> 'label' AS VARCHAR) IS NOT NULL
                ORDER BY 1
                """
            ).fetchall()
        ]

    return {
        "min_day": str(min_day) if min_day else None,
        "max_day": str(max_day) if max_day else None,
        "categories": categories,
        "versions": versions,
        "issue_labels": issue_labels,
    }


def search_reviews(
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    category: str | None = None,
    issue_label: str | None = None,
    version: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> tuple[pd.DataFrame, int]:
    """Return paginated review drilldown rows and total filtered count."""
    start = _to_date_string(start_date)
    end = _to_date_string(end_date)
    safe_page = max(int(page), 1)
    safe_page_size = max(1, min(int(page_size), 200))
    offset = (safe_page - 1) * safe_page_size

    where_clauses = ["1=1"]
    params: list[Any] = []

    if start:
        where_clauses.append("DATE(r.at_ts) >= ?")
        params.append(start)
    if end:
        where_clauses.append("DATE(r.at_ts) <= ?")
        params.append(end)
    if category:
        where_clauses.append("COALESCE(e.category_taxonomy, 'Other') = ?")
        params.append(category)
    if version:
        where_clauses.append("r.app_version = ?")
        params.append(version)
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

    where_sql = " AND ".join(where_clauses)

    count_query = f"""
        SELECT COUNT(*)
        FROM reviews_raw r
        JOIN reviews_enriched e USING (review_id)
        WHERE {where_sql}
    """

    data_query = f"""
        SELECT
            r.review_id,
            DATE(r.at_ts) AS day,
            r.app_version,
            COALESCE(e.category_taxonomy, 'Other') AS category_taxonomy,
            COALESCE(e.sentiment_label, 'unknown') AS sentiment_label,
            COALESCE(e.severity_band, 'unknown') AS severity_band,
            ROUND(COALESCE(e.severity_score, 0.0), 3) AS severity_score,
            r.score,
            COALESCE(r.thumbs_up, 0) AS thumbs_up,
            COALESCE(
                (
                    SELECT string_agg(CAST(je.value ->> 'label' AS VARCHAR), ', ')
                    FROM json_each(COALESCE(e.issues_json, '[]')) je
                    WHERE CAST(je.value ->> 'label' AS VARCHAR) IS NOT NULL
                ),
                ''
            ) AS issues,
            r.content
        FROM reviews_raw r
        JOIN reviews_enriched e USING (review_id)
        WHERE {where_sql}
        ORDER BY DATE(r.at_ts) DESC, COALESCE(e.severity_score, 0.0) DESC, r.review_id
        LIMIT ? OFFSET ?
    """

    with duckdb.connect(str(DUCKDB_PATH), read_only=True) as conn:
        total_count = int(conn.execute(count_query, params).fetchone()[0])
        rows = conn.execute(data_query, [*params, safe_page_size, offset]).fetchall()

    columns = [
        "review_id",
        "day",
        "app_version",
        "category_taxonomy",
        "sentiment_label",
        "severity_band",
        "severity_score",
        "score",
        "thumbs_up",
        "issues",
        "content",
    ]
    return pd.DataFrame(rows, columns=columns), total_count
