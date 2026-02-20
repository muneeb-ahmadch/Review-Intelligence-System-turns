from __future__ import annotations

import re
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from pipeline.db import get_connection
from pipeline.migrations import run_migrations

POSITIVE_WORDS: tuple[str, ...] = (
    "great",
    "love",
    "smooth",
    "fast",
    "amazing",
    "excellent",
    "awesome",
    "good",
    "helpful",
    "easy",
    "perfect",
    "reliable",
)

NEGATIVE_WORDS: tuple[str, ...] = (
    "terrible",
    "doesn't work",
    "doesnt work",
    "failed",
    "worst",
    "scam",
    "uninstall",
    "bad",
    "awful",
    "error",
    "broken",
    "crash",
    "stuck",
    "unable",
    "declined",
    "not working",
)

WORD_RE = re.compile(r"[a-z']+")


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _rating_prior(score: int | None) -> float:
    if score is None:
        return 0.0
    if score in {1, 2}:
        return -1.0
    if score == 3:
        return 0.0
    if score in {4, 5}:
        return 1.0
    return 0.0


def _count_phrase_hits(text: str, phrases: tuple[str, ...]) -> int:
    return sum(1 for p in phrases if p in text)


def _lexicon_score(text: str) -> float:
    txt = text.lower()
    tokens = WORD_RE.findall(txt)
    positive_single_words = {w for w in POSITIVE_WORDS if " " not in w}
    negative_single_words = {w for w in NEGATIVE_WORDS if " " not in w}

    positive_hits = _count_phrase_hits(txt, POSITIVE_WORDS)
    negative_hits = _count_phrase_hits(txt, NEGATIVE_WORDS)

    # Negation handling for patterns like "not good" or "never works".
    for i, token in enumerate(tokens[:-1]):
        if token not in {"not", "never"}:
            continue

        nxt = tokens[i + 1]
        if nxt in positive_single_words or nxt in {"work", "works", "working"}:
            negative_hits += 1
        elif nxt in negative_single_words:
            positive_hits += 1

    return float(positive_hits - negative_hits)


def _classify_sentiment(content: str | None, score: int | None) -> tuple[str, float]:
    text = (content or "").strip()
    prior = _rating_prior(score)
    lex = _lexicon_score(text)

    total_signal = (1.3 * prior) + (0.55 * lex)

    if total_signal <= -0.45:
        label = "negative"
    elif total_signal >= 0.45:
        label = "positive"
    else:
        label = "neutral"

    margin = abs(total_signal)
    confidence = _clamp(0.50 + (0.12 * margin), 0.50, 0.99)
    return label, confidence


def main() -> None:
    run_migrations()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT review_id, content, score, thumbs_up, category_raw, app_version, at_ts
            FROM reviews_raw
            """
        ).fetchall()

        updates: list[tuple[str, float, str]] = []
        for review_id, content, score, _thumbs_up, _category_raw, _app_version, _at_ts in rows:
            label, confidence = _classify_sentiment(content, score)
            updates.append((label, confidence, review_id))

        if updates:
            conn.executemany(
                """
                UPDATE reviews_enriched
                SET
                    sentiment_label = ?,
                    sentiment_confidence = ?,
                    sentiment_method = 'rule',
                    processed_at = CURRENT_TIMESTAMP
                WHERE review_id = ?
                """,
                updates,
            )

        enriched = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN sentiment_method = 'rule' THEN 1 ELSE 0 END) AS rule_rows,
                SUM(CASE WHEN sentiment_label = 'negative' THEN 1 ELSE 0 END) AS neg_rows
            FROM reviews_enriched
            """
        ).fetchone()

    print(
        "[02_enrich_sentiment] completed: "
        f"rows={enriched[0]}, rule_rows={enriched[1]}, negative_rows={enriched[2]}"
    )


if __name__ == "__main__":
    main()
