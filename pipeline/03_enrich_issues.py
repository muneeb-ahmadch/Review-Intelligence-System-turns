from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from pipeline.db import get_connection
from pipeline.migrations import run_migrations


@dataclass(frozen=True)
class IssueRule:
    label: str
    keyword_patterns: tuple[str, ...]
    regex_patterns: tuple[str, ...] = ()


ISSUE_RULES: tuple[IssueRule, ...] = (
    IssueRule(
        label="Transaction Failure",
        keyword_patterns=(
            "payment failed",
            "transfer failed",
            "transaction failed",
            "declined",
            "not going through",
            "chargeback",
            "pending forever",
            "refund not received",
        ),
        regex_patterns=(
            r"\b(payment|transfer|transaction|withdrawal|deposit)\b.{0,24}\b(fail(?:ed|ure)?|declin(?:e|ed)|error)\b",
        ),
    ),
    IssueRule(
        label="Login/Auth Issues",
        keyword_patterns=(
            "can't login",
            "cannot login",
            "unable to login",
            "otp not received",
            "2fa",
            "verification failed",
            "password reset",
            "face id",
            "fingerprint",
            "authentication error",
        ),
        regex_patterns=(
            r"\b(login|log in|signin|sign in|auth|authentication|otp|verification|password)\b.{0,24}\b(fail(?:ed|ure)?|error|stuck|not working)\b",
        ),
    ),
    IssueRule(
        label="Performance Issues",
        keyword_patterns=(
            "slow",
            "laggy",
            "freezes",
            "takes forever",
            "loading forever",
            "very sluggish",
            "unresponsive",
            "high battery usage",
            "overheating",
        ),
        regex_patterns=(
            r"\b(slow|lag|sluggish|freeze|stutter|unresponsive)\b",
        ),
    ),
    IssueRule(
        label="Glitches/Bugs",
        keyword_patterns=(
            "bug",
            "glitch",
            "crash",
            "crashes",
            "keeps crashing",
            "not working",
            "stuck on",
            "blank screen",
            "broken",
        ),
        regex_patterns=(
            r"\b(crash(?:es|ed|ing)?|bug(?:s)?|glitch(?:es)?|broken|stuck)\b",
        ),
    ),
    IssueRule(
        label="UI/UX Problems",
        keyword_patterns=(
            "hard to use",
            "confusing",
            "bad design",
            "poor layout",
            "cannot find",
            "too many steps",
            "ui issue",
            "ux issue",
            "navigation is bad",
        ),
        regex_patterns=(
            r"\b(ui|ux|layout|design|navigation)\b.{0,24}\b(bad|poor|confusing|hard|difficult)\b",
        ),
    ),
    IssueRule(
        label="Policy Complaints",
        keyword_patterns=(
            "fees are high",
            "hidden charges",
            "policy changed",
            "unfair policy",
            "terms changed",
            "suspended account",
            "blocked account",
            "compliance hold",
        ),
        regex_patterns=(
            r"\b(fee|charges|policy|terms|compliance|kyc)\b.{0,24}\b(unfair|bad|changed|problem)\b",
        ),
    ),
    IssueRule(
        label="Feature Requests",
        keyword_patterns=(
            "please add",
            "need feature",
            "would like",
            "it would be great",
            "wish you had",
            "add dark mode",
            "add export",
            "support apple pay",
        ),
        regex_patterns=(
            r"\b(add|need|wish|request|feature)\b.{0,28}\b(feature|option|support|mode|integration)\b",
        ),
    ),
    IssueRule(
        label="Customer Support",
        keyword_patterns=(
            "support not responding",
            "customer service",
            "no response",
            "chat support",
            "help desk",
            "agent was rude",
            "ticket unresolved",
            "no one helped",
        ),
        regex_patterns=(
            r"\b(support|customer service|agent|ticket|help desk)\b.{0,24}\b(no response|unhelpful|rude|slow|bad)\b",
        ),
    ),
)

NEAR_FAILURE_RE = re.compile(r"\b(can't|cant|cannot|failed|failure|error)\b", flags=re.IGNORECASE)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _find_keyword_hits(text: str, phrase: str) -> list[tuple[int, int]]:
    escaped = re.escape(phrase)
    pattern = re.compile(rf"\b{escaped}\b", flags=re.IGNORECASE)
    return [m.span() for m in pattern.finditer(text)]


def _find_regex_hits(text: str, pattern: str) -> list[tuple[int, int]]:
    regex = re.compile(pattern, flags=re.IGNORECASE)
    return [m.span() for m in regex.finditer(text)]


def _has_near_failure(keyword_spans: list[tuple[int, int]], text: str, max_gap_chars: int = 40) -> bool:
    if not keyword_spans:
        return False

    failure_spans = [m.span() for m in NEAR_FAILURE_RE.finditer(text)]
    if not failure_spans:
        return False

    for k_start, k_end in keyword_spans:
        for f_start, f_end in failure_spans:
            if f_end < k_start:
                gap = k_start - f_end
            elif k_end < f_start:
                gap = f_start - k_end
            else:
                return True
            if gap <= max_gap_chars:
                return True
    return False


def _classify_issues(content: str | None) -> list[dict[str, object]]:
    text = (content or "").strip().lower()
    if not text:
        return []

    found: list[dict[str, object]] = []
    for rule in ISSUE_RULES:
        all_spans: list[tuple[int, int]] = []
        evidence: list[str] = []

        for phrase in rule.keyword_patterns:
            spans = _find_keyword_hits(text, phrase)
            if spans:
                all_spans.extend(spans)
                evidence.append(phrase)

        for regex_pattern in rule.regex_patterns:
            spans = _find_regex_hits(text, regex_pattern)
            if spans:
                all_spans.extend(spans)
                evidence.append(f"regex:{regex_pattern}")

        hit_count = len(all_spans)
        if hit_count == 0:
            continue

        confidence = 0.60
        if hit_count >= 2:
            confidence += 0.10
        if _has_near_failure(all_spans, text):
            confidence += 0.10
        confidence = min(0.85, confidence)

        found.append(
            {
                "label": rule.label,
                "confidence": round(confidence, 2),
                "evidence": _dedupe_preserve_order(evidence),
            }
        )

    return found


def main() -> None:
    run_migrations()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT review_id, content
            FROM reviews_raw
            """
        ).fetchall()

        updates: list[tuple[str, str]] = []
        for review_id, content in rows:
            issues = _classify_issues(content)
            issues_json = json.dumps(issues if issues else [], ensure_ascii=True)
            updates.append((issues_json, review_id))

        if updates:
            conn.executemany(
                """
                UPDATE reviews_enriched
                SET
                    issues_json = ?,
                    issues_method = 'rule',
                    processed_at = CURRENT_TIMESTAMP
                WHERE review_id = ?
                """,
                updates,
            )

        summary = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN issues_method = 'rule' THEN 1 ELSE 0 END) AS rule_rows,
                SUM(CASE WHEN COALESCE(issues_json, '[]') <> '[]' THEN 1 ELSE 0 END) AS issue_rows
            FROM reviews_enriched
            """
        ).fetchone()

    print(
        "[03_enrich_issues] completed: "
        f"rows={summary[0]}, rule_rows={summary[1]}, rows_with_issues={summary[2]}"
    )


if __name__ == "__main__":
    main()
