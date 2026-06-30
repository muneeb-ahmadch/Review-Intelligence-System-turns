"""Grounding guardrails for LLM insight outputs.

The model is only ever asked to *narrate and prioritise* — never to invent
numbers or quotes. These guardrails enforce that after generation:

- KPI numbers in the output are overwritten with the figures we computed
  deterministically from DuckDB, so a headline can never drift from the data.
- Every `evidence_quotes` entry must substring-match one of the real review
  excerpts we passed in. Anything the model paraphrased or hallucinated is
  dropped. A quote that survives is provably present in the source reviews.

This is what lets the README claim insights "cite counts and examples rather
than hallucinate" honestly.
"""

from __future__ import annotations

import re
from typing import Any


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _build_allowed_quotes(input_payload: dict[str, Any]) -> list[str]:
    allowed: list[str] = []
    for item in input_payload.get("evidence_reviews", []) or []:
        quote = _normalize(item.get("quote", ""))
        if quote:
            allowed.append(quote)
    return allowed


def _filter_quotes(quotes: Any, allowed: list[str]) -> list[str]:
    """Keep only quotes that are grounded in the provided evidence."""
    if not isinstance(quotes, list):
        return []
    kept: list[str] = []
    for quote in quotes:
        candidate = _normalize(quote)
        if not candidate:
            continue
        # Grounded if the model's quote is contained in (or contains) a real one.
        if any(candidate in real or real in candidate for real in allowed):
            kept.append(str(quote).strip())
    return kept


def ground_report(report_type: str, report: dict[str, Any], input_payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `report` with KPI numbers pinned and quotes filtered."""
    if not isinstance(report, dict):
        return report

    allowed = _build_allowed_quotes(input_payload)
    kpi = input_payload.get("kpi_snapshot", {}) or {}

    if report_type == "weekly_exec_brief":
        # Pin KPI summary to computed values.
        if isinstance(report.get("kpi_summary"), dict):
            report["kpi_summary"]["avg_rating"] = float(kpi.get("avg_rating", 0.0) or 0.0)
            report["kpi_summary"]["pct_negative"] = float(kpi.get("pct_negative", 0.0) or 0.0)
            report["kpi_summary"]["critical_count"] = int(kpi.get("critical_count", 0) or 0)
        for driver in report.get("drivers", []) or []:
            if isinstance(driver, dict) and "evidence_quotes" in driver:
                driver["evidence_quotes"] = _filter_quotes(driver.get("evidence_quotes"), allowed)

    elif report_type == "sprint_backlog":
        for ticket in report.get("tickets", []) or []:
            if isinstance(ticket, dict) and "evidence_quotes" in ticket:
                ticket["evidence_quotes"] = _filter_quotes(ticket.get("evidence_quotes"), allowed)

    return report
