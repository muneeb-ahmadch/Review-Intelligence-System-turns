from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from pipeline.db import get_connection
from pipeline.migrations import run_migrations


ROOT_DIR = Path(__file__).resolve().parent.parent
TAXONOMY_MAP_PATH = ROOT_DIR / "analytics" / "taxonomy_map.json"
EMPTY_CONTENT_MARKER = "[EMPTY_REVIEW]"


def _load_taxonomy_map(path: Path) -> tuple[list[tuple[str, str]], str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("taxonomy_map.json must contain a JSON object")

    fallback = raw.get("__fallback__", "Other")
    if not isinstance(fallback, str) or not fallback.strip():
        fallback = "Other"

    mappings: list[tuple[str, str]] = []
    for key, value in raw.items():
        if key == "__fallback__":
            continue
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        normalized_key = key.strip().lower()
        if normalized_key:
            mappings.append((normalized_key, value.strip() or fallback))

    return mappings, fallback


def _category_key_sql(expression: str) -> str:
    return (
        "regexp_replace("
        "regexp_replace(lower(trim(coalesce(" + expression + ", ''))), '[^a-z0-9]+', '_', 'g'),"
        "'^_+|_+$', '', 'g'"
        ")"
    )


def main() -> None:
    run_migrations()
    mappings, fallback = _load_taxonomy_map(TAXONOMY_MAP_PATH)

    with get_connection() as conn:
        conn.execute("DROP TABLE IF EXISTS taxonomy_map_tmp")
        conn.execute(
            """
            CREATE TEMP TABLE taxonomy_map_tmp (
                category_key VARCHAR PRIMARY KEY,
                category_taxonomy VARCHAR NOT NULL
            )
            """
        )
        if mappings:
            conn.executemany(
                "INSERT INTO taxonomy_map_tmp (category_key, category_taxonomy) VALUES (?, ?)",
                mappings,
            )

        category_key_expr = _category_key_sql("r.category_raw")
        conn.execute("DROP TABLE IF EXISTS stage_normalized")
        conn.execute(
            f"""
            CREATE TEMP TABLE stage_normalized AS
            SELECT
                r.review_id,
                CASE
                    WHEN r.content IS NULL OR LENGTH(TRIM(r.content)) = 0 THEN '{EMPTY_CONTENT_MARKER}'
                    ELSE regexp_replace(TRIM(r.content), '\\\\s+', ' ', 'g')
                END AS content_clean,
                COALESCE(t.category_taxonomy, '{fallback}') AS category_taxonomy
            FROM reviews_raw r
            LEFT JOIN taxonomy_map_tmp t
                ON {category_key_expr} = t.category_key
            """
        )

        conn.execute(
            """
            UPDATE reviews_raw AS r
            SET content = s.content_clean
            FROM stage_normalized AS s
            WHERE r.review_id = s.review_id
            """
        )

        conn.execute(
            """
            INSERT OR REPLACE INTO reviews_enriched (
                review_id,
                category_taxonomy,
                sentiment_label,
                sentiment_confidence,
                sentiment_method,
                issues_json,
                issues_method,
                severity_score,
                severity_band,
                churn_user_score,
                churn_user_tier,
                churn_user_rationale,
                processed_at
            )
            SELECT
                review_id,
                category_taxonomy,
                NULL AS sentiment_label,
                NULL AS sentiment_confidence,
                NULL AS sentiment_method,
                NULL AS issues_json,
                NULL AS issues_method,
                NULL AS severity_score,
                NULL AS severity_band,
                NULL AS churn_user_score,
                NULL AS churn_user_tier,
                NULL AS churn_user_rationale,
                CURRENT_TIMESTAMP AS processed_at
            FROM stage_normalized
            """
        )

        conn.execute(
            """
            CREATE OR REPLACE VIEW reviews_raw_daily AS
            SELECT
                review_id,
                user_name,
                content,
                score,
                thumbs_up,
                review_created_version,
                at_ts,
                DATE(at_ts) AS day,
                app_version,
                category_raw
            FROM reviews_raw
            """
        )

        raw_count = conn.execute("SELECT COUNT(*) FROM reviews_raw").fetchone()[0]
        enriched_count = conn.execute("SELECT COUNT(*) FROM reviews_enriched").fetchone()[0]
        empty_count = conn.execute(
            "SELECT COUNT(*) FROM reviews_raw WHERE content = ?",
            [EMPTY_CONTENT_MARKER],
        ).fetchone()[0]

    print(
        "[01_normalize] completed: "
        f"raw_rows={raw_count}, enriched_rows={enriched_count}, "
        f"empty_content_strategy=keep_with_marker('{EMPTY_CONTENT_MARKER}'), "
        f"empty_rows={empty_count}, category_fallback='{fallback}'"
    )


if __name__ == "__main__":
    main()
