from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from pipeline.db import get_connection
from pipeline.migrations import run_migrations


CSV_FILES: tuple[tuple[str, Path], ...] = (
    ("average", Path("data/converted_reviews_average.csv")),
    ("bad", Path("data/converted_reviews_bad.csv")),
    ("good", Path("data/converted_reviews_good.csv")),
)

TARGET_COLUMNS: tuple[str, ...] = (
    "review_id",
    "user_name",
    "content",
    "score",
    "thumbs_up",
    "review_created_version",
    "at_ts",
    "app_version",
    "category_raw",
)

# canonical_target -> acceptable source header variants
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "review_id": ("reviewId", "review_id", "id", "reviewid"),
    "user_name": ("userName", "user_name", "username", "user"),
    "content": ("content", "review", "review_text", "text", "comment"),
    "score": ("score", "rating", "stars", "star_rating"),
    "thumbs_up": ("thumbsUpCount", "thumbs_up", "thumbsupcount", "helpful_count"),
    "review_created_version": (
        "reviewCreatedVersion",
        "review_created_version",
        "reviewversion",
    ),
    "at_ts": ("at", "at_ts", "created_at", "timestamp", "date"),
    "app_version": ("appVersion", "app_version", "version", "appversion"),
    "category_raw": ("category", "category_raw", "categoryname", "topic"),
}


def _normalize_header(name: str) -> str:
    return "".join(ch.lower() for ch in name if ch.isalnum())


def _q(identifier: str) -> str:
    return f'"{identifier.replace("\"", "\"\"")}"'


def _resolve_mapping(headers: Iterable[str]) -> dict[str, str]:
    header_list = list(headers)
    normalized_lookup = {_normalize_header(h): h for h in header_list}

    resolved: dict[str, str] = {}
    missing: list[str] = []

    for target, aliases in COLUMN_ALIASES.items():
        source_name = None
        for alias in aliases:
            source_name = normalized_lookup.get(_normalize_header(alias))
            if source_name is not None:
                break
        if source_name is None:
            missing.append(target)
        else:
            resolved[target] = source_name

    if missing:
        raise ValueError(f"Missing required columns for mapping: {', '.join(missing)}")

    return resolved


def _build_stage_select(mapping: dict[str, str]) -> str:
    at_source = mapping["at_ts"]

    return f"""
        SELECT
            CAST(NULLIF(TRIM({_q(mapping['review_id'])}), '') AS VARCHAR) AS review_id,
            CAST(NULLIF(TRIM({_q(mapping['user_name'])}), '') AS VARCHAR) AS user_name,
            CAST(NULLIF(TRIM({_q(mapping['content'])}), '') AS VARCHAR) AS content,
            TRY_CAST(NULLIF(TRIM({_q(mapping['score'])}), '') AS INTEGER) AS score,
            TRY_CAST(NULLIF(TRIM({_q(mapping['thumbs_up'])}), '') AS INTEGER) AS thumbs_up,
            CAST(NULLIF(TRIM({_q(mapping['review_created_version'])}), '') AS VARCHAR) AS review_created_version,
            COALESCE(
                TRY_STRPTIME(NULLIF(TRIM({_q(at_source)}), ''), '%Y-%m-%d %H:%M:%S'),
                TRY_STRPTIME(NULLIF(TRIM({_q(at_source)}), ''), '%Y-%m-%d %H:%M'),
                TRY_STRPTIME(NULLIF(TRIM({_q(at_source)}), ''), '%Y-%m-%d')
            ) AS at_ts,
            CAST(NULLIF(TRIM({_q(mapping['app_version'])}), '') AS VARCHAR) AS app_version,
            CAST(NULLIF(TRIM({_q(mapping['category_raw'])}), '') AS VARCHAR) AS category_raw
        FROM src
    """


def _load_file(conn, label: str, csv_path: Path) -> int:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    conn.execute("DROP TABLE IF EXISTS src")
    conn.execute(
        "CREATE TEMP TABLE src AS SELECT * FROM read_csv_auto(?, header=true, all_varchar=true)",
        [str(csv_path)],
    )

    headers = [row[0] for row in conn.execute("DESCRIBE src").fetchall()]
    mapping = _resolve_mapping(headers)
    mapping_log = ", ".join(f"{src}->{dst}" for dst, src in mapping.items())
    print(f"Mapping {label}: {mapping_log}")

    conn.execute("DROP TABLE IF EXISTS stage_file")
    conn.execute(f"CREATE TEMP TABLE stage_file AS {_build_stage_select(mapping)}")

    row_count = conn.execute("SELECT COUNT(*) FROM stage_file").fetchone()[0]
    print(f"Loaded {label}: {row_count} rows")

    conn.execute("INSERT INTO stage_all SELECT * FROM stage_file")
    return row_count


def main() -> None:
    run_migrations()

    with get_connection() as conn:
        conn.execute("DROP TABLE IF EXISTS stage_all")
        conn.execute(
            """
            CREATE TEMP TABLE stage_all (
                review_id VARCHAR,
                user_name VARCHAR,
                content VARCHAR,
                score INTEGER,
                thumbs_up INTEGER,
                review_created_version VARCHAR,
                at_ts TIMESTAMP,
                app_version VARCHAR,
                category_raw VARCHAR
            )
            """
        )

        for label, csv_path in CSV_FILES:
            _load_file(conn, label, csv_path)

        combined_count = conn.execute("SELECT COUNT(*) FROM stage_all").fetchone()[0]
        print(f"Combined: {combined_count}")

        conn.execute("DROP TABLE IF EXISTS stage_deduped")
        conn.execute(
            """
            CREATE TEMP TABLE stage_deduped AS
            SELECT
                review_id,
                user_name,
                content,
                score,
                thumbs_up,
                review_created_version,
                at_ts,
                app_version,
                category_raw
            FROM (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY review_id
                        ORDER BY at_ts DESC NULLS LAST
                    ) AS rn
                FROM stage_all
                WHERE review_id IS NOT NULL
            ) t
            WHERE rn = 1
            """
        )

        deduped_count = conn.execute("SELECT COUNT(*) FROM stage_deduped").fetchone()[0]
        deduped_out = combined_count - deduped_count
        print(f"Deduped: {combined_count} - {deduped_out} = {deduped_count}")

        conn.execute(f"INSERT OR REPLACE INTO reviews_raw ({', '.join(TARGET_COLUMNS)}) SELECT {', '.join(TARGET_COLUMNS)} FROM stage_deduped")
        print(f"Inserted into reviews_raw: {deduped_count}")


if __name__ == "__main__":
    main()
