"""Step 08 — trend + anomaly detection over the daily aggregates.

Runs after step 06 (daily aggregates exist). For each metric we track
(pct_negative, critical_count) we compute a rolling 7-day baseline (mean + std
over the trailing window) and flag a day when it deviates by >= 2 standard
deviations. To avoid flagging noise on the many low-volume days in this dataset,
a day must also have at least MIN_VOLUME reviews to qualify.

Flags are written back to daily_aggregates.anomaly_flags_json as a JSON object,
e.g. {"pct_negative": {"value": 0.61, "baseline": 0.34, "z": 2.4}}. The Trends
tab reads these to build its anomaly list.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from pipeline.db import get_connection
from pipeline.migrations import run_migrations

MIN_VOLUME = 8          # ignore days with too few reviews to be meaningful
WINDOW = 7              # trailing days for the rolling baseline
Z_THRESHOLD = 2.0       # flag deviations beyond this many std devs

METRICS = ("pct_negative", "critical_count")


def _detect(rows: list[dict]) -> dict[str, dict]:
    """Return {day_iso: {metric: {value, baseline, z}}} for flagged days."""
    flags: dict[str, dict] = {}

    for metric in METRICS:
        series = [(r["day"], float(r[metric] or 0.0), int(r["total_reviews"] or 0)) for r in rows]
        for i, (day, value, volume) in enumerate(series):
            if volume < MIN_VOLUME or i < WINDOW:
                continue
            window = [v for (_, v, _) in series[i - WINDOW:i]]
            mean = sum(window) / len(window)
            variance = sum((v - mean) ** 2 for v in window) / len(window)
            std = variance ** 0.5
            if std <= 1e-9:
                continue
            z = (value - mean) / std
            if abs(z) >= Z_THRESHOLD:
                flags.setdefault(str(day), {})[metric] = {
                    "value": round(value, 4),
                    "baseline": round(mean, 4),
                    "z": round(z, 2),
                }

    return flags


def main() -> None:
    run_migrations()

    with get_connection() as conn:
        rows = [
            {"day": r[0], "total_reviews": r[1], "pct_negative": r[2], "critical_count": r[3]}
            for r in conn.execute(
                """
                SELECT day, total_reviews, pct_negative, critical_count
                FROM daily_aggregates
                ORDER BY day
                """
            ).fetchall()
        ]

        flags = _detect(rows)

        # Reset then write the flagged days.
        conn.execute("UPDATE daily_aggregates SET anomaly_flags_json = '{}'")
        for day_iso, metric_flags in flags.items():
            conn.execute(
                "UPDATE daily_aggregates SET anomaly_flags_json = ? WHERE day = ?",
                [json.dumps(metric_flags, separators=(",", ":")), day_iso],
            )

        n_flagged = sum(len(v) for v in flags.values())
        print(f"[08_trends_anomalies] flagged {len(flags)} days, {n_flagged} metric anomalies")


if __name__ == "__main__":
    main()
