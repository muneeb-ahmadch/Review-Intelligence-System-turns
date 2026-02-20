from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from pipeline.db import get_connection


CREATE_TABLE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS reviews_raw (
        review_id VARCHAR PRIMARY KEY,
        user_name VARCHAR,
        content VARCHAR,
        score INTEGER,
        thumbs_up INTEGER,
        review_created_version VARCHAR,
        at_ts TIMESTAMP,
        app_version VARCHAR,
        category_raw VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reviews_enriched (
        review_id VARCHAR PRIMARY KEY,
        category_taxonomy VARCHAR,
        sentiment_label VARCHAR,
        sentiment_confidence DOUBLE,
        sentiment_method VARCHAR,
        issues_json VARCHAR,
        issues_method VARCHAR,
        severity_score DOUBLE,
        severity_band VARCHAR,
        churn_user_score DOUBLE,
        churn_user_tier VARCHAR,
        churn_user_rationale VARCHAR,
        processed_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_aggregates (
        day DATE PRIMARY KEY,
        total_reviews INTEGER,
        avg_rating DOUBLE,
        pct_negative DOUBLE,
        pct_positive DOUBLE,
        critical_count INTEGER,
        top_issues_json VARCHAR,
        churn_high_users INTEGER,
        anomaly_flags_json VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS version_aggregates (
        app_version VARCHAR PRIMARY KEY,
        first_seen_day DATE,
        last_seen_day DATE,
        total_reviews INTEGER,
        avg_rating DOUBLE,
        pct_negative DOUBLE,
        critical_count INTEGER,
        issue_breakdown_json VARCHAR,
        category_breakdown_json VARCHAR
    )
    """,
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
    """,
)


def run_migrations() -> None:
    with get_connection() as conn:
        for statement in CREATE_TABLE_STATEMENTS:
            conn.execute(statement)


def main() -> None:
    run_migrations()
    print("[migrations] ensured tables: reviews_raw, reviews_enriched, daily_aggregates, version_aggregates, insight_reports")


if __name__ == "__main__":
    main()
