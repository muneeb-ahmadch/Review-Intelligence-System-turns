from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pipeline.db import get_connection


def _run(script_path: str) -> None:
    subprocess.run(
        [sys.executable, script_path],
        cwd=ROOT_DIR,
        check=True,
    )


def _prepare_pipeline_state() -> None:
    _run("pipeline/migrations.py")
    _run("pipeline/00_ingest.py")
    _run("pipeline/01_normalize.py")
    _run("pipeline/02_enrich_sentiment.py")
    _run("pipeline/04_score_severity.py")


def test_severity_monotonicity_by_rating() -> None:
    _prepare_pipeline_state()

    with get_connection(read_only=True) as conn:
        avg_sev_score_1 = conn.execute(
            """
            SELECT AVG(e.severity_score)
            FROM reviews_raw r
            JOIN reviews_enriched e USING (review_id)
            WHERE r.score = 1
            """
        ).fetchone()[0]
        avg_sev_score_5 = conn.execute(
            """
            SELECT AVG(e.severity_score)
            FROM reviews_raw r
            JOIN reviews_enriched e USING (review_id)
            WHERE r.score = 5
            """
        ).fetchone()[0]

    assert avg_sev_score_1 is not None
    assert avg_sev_score_5 is not None
    assert avg_sev_score_1 > avg_sev_score_5


def test_negative_sentiment_rate_for_low_ratings() -> None:
    _prepare_pipeline_state()

    with get_connection(read_only=True) as conn:
        pct_negative = conn.execute(
            """
            SELECT
                AVG(
                    CASE WHEN e.sentiment_label = 'negative' THEN 1.0 ELSE 0.0 END
                ) AS pct_negative
            FROM reviews_raw r
            JOIN reviews_enriched e USING (review_id)
            WHERE r.score IN (1, 2)
            """
        ).fetchone()[0]

    assert pct_negative is not None
    assert pct_negative >= 0.70
