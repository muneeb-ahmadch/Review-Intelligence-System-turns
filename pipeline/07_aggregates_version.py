from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from pipeline.db import get_connection
from pipeline.migrations import run_migrations


ROOT_DIR = Path(__file__).resolve().parent.parent
SQL_PATH = ROOT_DIR / "analytics" / "sql" / "version_breakdown.sql"


def main() -> None:
    run_migrations()
    query = SQL_PATH.read_text(encoding="utf-8")

    with get_connection() as conn:
        conn.execute("DROP TABLE IF EXISTS stage_version_aggregates")
        conn.execute(f"CREATE TEMP TABLE stage_version_aggregates AS {query}")

        stage_count = conn.execute("SELECT COUNT(*) FROM stage_version_aggregates").fetchone()[0]
        conn.execute(
            """
            INSERT OR REPLACE INTO version_aggregates (
                app_version,
                first_seen_day,
                last_seen_day,
                total_reviews,
                avg_rating,
                pct_negative,
                critical_count,
                issue_breakdown_json,
                category_breakdown_json
            )
            SELECT
                app_version,
                first_seen_day,
                last_seen_day,
                total_reviews,
                avg_rating,
                pct_negative,
                critical_count,
                issue_breakdown_json,
                category_breakdown_json
            FROM stage_version_aggregates
            """
        )

        total_count = conn.execute("SELECT COUNT(*) FROM version_aggregates").fetchone()[0]

    print(
        "[07_aggregates_version] completed: "
        f"stage_rows={stage_count}, version_aggregates_rows={total_count}"
    )


if __name__ == "__main__":
    main()
