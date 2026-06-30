"""Step 05 — deterministic per-user churn-risk heuristic.

Churn risk is a *heuristic*, not a model. For every user we combine signals that
are already in the data: how negative their reviews are, how severe, whether they
hit repeated failures, and whether they voiced explicit churn intent
("uninstall", "switching", "close account"...). The score is a transparent
weighted sum so the rationale we store is literally the formula's inputs.

Outputs:
  - a `user_churn` table (one row per user) used by the daily aggregates, and
  - churn_user_score / churn_user_tier / churn_user_rationale written back onto
    reviews_enriched so drilldowns can show it.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from pipeline.db import get_connection
from pipeline.migrations import run_migrations

# Explicit churn-intent phrases users write when they're about to leave.
CHURN_INTENT_TERMS: tuple[str, ...] = (
    "uninstall",
    "deleting",
    "deleted the app",
    "switching",
    "switch to",
    "close account",
    "closing my account",
    "cancel",
    "never again",
    "worst app",
    "leaving",
)

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


def _like_any(column: str, terms: tuple[str, ...]) -> str:
    # Double single quotes so terms like "can't" are valid SQL string literals.
    clauses = " OR ".join(
        f"LOWER({column}) LIKE '%{term.replace(chr(39), chr(39) * 2)}%'" for term in terms
    )
    return f"({clauses})"


def main() -> None:
    run_migrations()

    churn_intent_expr = _like_any("r.content", CHURN_INTENT_TERMS)
    failure_expr = _like_any("r.content", FAILURE_TERMS)

    user_churn_sql = f"""
        WITH per_user AS (
            SELECT
                r.user_name AS user_name,
                COUNT(*) AS n_reviews,
                AVG(CASE WHEN e.sentiment_label = 'negative' THEN 1.0 ELSE 0.0 END) AS pct_negative,
                AVG(COALESCE(e.severity_score, 0.0)) AS avg_severity,
                SUM(CASE WHEN {failure_expr} THEN 1 ELSE 0 END) AS failure_count,
                MAX(CASE WHEN {churn_intent_expr} THEN 1 ELSE 0 END) AS churn_intent
            FROM reviews_raw r
            JOIN reviews_enriched e USING (review_id)
            WHERE r.user_name IS NOT NULL
            GROUP BY r.user_name
        ),
        scored AS (
            SELECT
                user_name,
                n_reviews,
                pct_negative,
                avg_severity,
                failure_count,
                churn_intent,
                LEAST(1.0, GREATEST(0.0,
                    0.35 * pct_negative
                    + 0.30 * avg_severity
                    + 0.20 * churn_intent
                    + 0.15 * LEAST(1.0, failure_count / 3.0)
                )) AS churn_score
            FROM per_user
        )
        SELECT
            user_name,
            n_reviews,
            ROUND(churn_score, 4) AS churn_score,
            CASE
                WHEN churn_score > 0.66 THEN 'high'
                WHEN churn_score >= 0.33 THEN 'med'
                ELSE 'low'
            END AS churn_tier,
            (
                'reviews=' || n_reviews
                || ', negative=' || CAST(ROUND(pct_negative * 100, 0) AS INTEGER) || '%'
                || ', avg_severity=' || ROUND(avg_severity, 2)
                || ', failures=' || failure_count
                || CASE WHEN churn_intent = 1 THEN ', explicit churn intent' ELSE '' END
            ) AS churn_rationale
        FROM scored
    """

    with get_connection() as conn:
        conn.execute("DROP TABLE IF EXISTS user_churn")
        conn.execute(f"CREATE TABLE user_churn AS {user_churn_sql}")

        total_users = conn.execute("SELECT COUNT(*) FROM user_churn").fetchone()[0]
        high_users = conn.execute("SELECT COUNT(*) FROM user_churn WHERE churn_tier = 'high'").fetchone()[0]
        print(f"[05_user_churn] scored {total_users} users ({high_users} high-risk)")

        conn.execute(
            """
            UPDATE reviews_enriched AS e
            SET churn_user_score = uc.churn_score,
                churn_user_tier = uc.churn_tier,
                churn_user_rationale = uc.churn_rationale
            FROM reviews_raw r, user_churn uc
            WHERE e.review_id = r.review_id
              AND r.user_name = uc.user_name
            """
        )
        updated = conn.execute(
            "SELECT COUNT(*) FROM reviews_enriched WHERE churn_user_tier IS NOT NULL"
        ).fetchone()[0]
        print(f"[05_user_churn] wrote churn fields onto {updated} enriched reviews")


if __name__ == "__main__":
    main()
