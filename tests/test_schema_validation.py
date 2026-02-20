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


def test_schema_validation() -> None:
    _run("pipeline/migrations.py")
    _run("pipeline/00_ingest.py")
    _run("pipeline/01_normalize.py")

    with get_connection(read_only=True) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main'
                """
            ).fetchall()
        }
        assert "reviews_raw" in tables
        assert "reviews_enriched" in tables

        raw_count = conn.execute("SELECT COUNT(*) FROM reviews_raw").fetchone()[0]
        enriched_count = conn.execute("SELECT COUNT(*) FROM reviews_enriched").fetchone()[0]

    assert raw_count > 0
    assert enriched_count == raw_count
