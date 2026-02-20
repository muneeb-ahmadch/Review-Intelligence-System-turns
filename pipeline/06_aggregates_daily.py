from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from pipeline.db import get_connection
from pipeline.migrations import run_migrations


ROOT_DIR = Path(__file__).resolve().parent.parent
SQL_PATH = ROOT_DIR / "analytics" / "sql" / "daily_kpis.sql"


def main() -> None:
    run_migrations()
    query = SQL_PATH.read_text(encoding="utf-8")

    with get_connection() as conn:
        conn.execute("DROP TABLE IF EXISTS stage_daily_aggregates")
        conn.execute(f"CREATE TEMP TABLE stage_daily_aggregates AS {query}")

        stage_count = conn.execute("SELECT COUNT(*) FROM stage_daily_aggregates").fetchone()[0]
        conn.execute(
            """
            INSERT OR REPLACE INTO daily_aggregates (
                day,
                total_reviews,
                avg_rating,
                pct_negative,
                pct_positive,
                critical_count,
                top_issues_json,
                churn_high_users,
                anomaly_flags_json
            )
            SELECT
                day,
                total_reviews,
                avg_rating,
                pct_negative,
                pct_positive,
                critical_count,
                top_issues_json,
                churn_high_users,
                anomaly_flags_json
            FROM stage_daily_aggregates
            """
        )

        total_count = conn.execute("SELECT COUNT(*) FROM daily_aggregates").fetchone()[0]
        top_issue_preview = conn.execute(
            """
            SELECT day, top_issues_json
            FROM daily_aggregates
            WHERE top_issues_json <> '[]'
            ORDER BY day DESC
            LIMIT 3
            """
        ).fetchall()

    print(f"[06_aggregates_daily] top issues preview (latest 3 days): {top_issue_preview}")
    print(
        "[06_aggregates_daily] completed: "
        f"stage_rows={stage_count}, daily_aggregates_rows={total_count}"
    )

if __name__ == "__main__":
    main()
