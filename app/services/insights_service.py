from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from analytics.evidence_quotes import get_evidence_quotes
from app.config import ROOT_DIR
from app.services.report_cache import get_or_create_report
from llm.json_enforcer import build_jsonschema_validator, call_json_with_retry, load_json_schema
from llm.ollama_client import DEFAULT_MODEL
from pipeline.db import get_connection


PROMPTS_DIR = ROOT_DIR / "llm" / "prompts"
SCHEMAS_DIR = ROOT_DIR / "llm" / "schemas"


def _to_date_string(value: str | date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _default_date_range() -> tuple[str, str]:
    try:
        with get_connection(read_only=True) as conn:
            min_day, max_day = conn.execute(
                "SELECT MIN(DATE(at_ts)), MAX(DATE(at_ts)) FROM reviews_raw"
            ).fetchone()
    except Exception:  # noqa: BLE001
        min_day, max_day = None, None

    if not min_day or not max_day:
        end = date.today()
        start = end - timedelta(days=6)
        return start.isoformat(), end.isoformat()

    end = max_day
    start = max(min_day, end - timedelta(days=6))
    return str(start), str(end)


def _normalize_scope(scope: dict[str, Any]) -> dict[str, Any]:
    input_scope = scope or {}
    start, end = _default_date_range()

    normalized = {
        "start_date": _to_date_string(input_scope.get("start_date")) or start,
        "end_date": _to_date_string(input_scope.get("end_date")) or end,
        "category": (input_scope.get("category") or "").strip(),
        "version": (input_scope.get("version") or "").strip(),
        "issue_label": (input_scope.get("issue_label") or "").strip(),
    }

    if normalized["start_date"] > normalized["end_date"]:
        normalized["start_date"], normalized["end_date"] = normalized["end_date"], normalized["start_date"]
    return normalized


def _build_filters(scope: dict[str, Any]) -> tuple[str, list[Any]]:
    where_clauses = ["DATE(r.at_ts) >= ?", "DATE(r.at_ts) <= ?"]
    params: list[Any] = [scope["start_date"], scope["end_date"]]

    if scope["category"]:
        where_clauses.append("COALESCE(e.category_taxonomy, 'Other') = ?")
        params.append(scope["category"])
    if scope["version"]:
        where_clauses.append("r.app_version = ?")
        params.append(scope["version"])
    if scope["issue_label"]:
        where_clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM json_each(COALESCE(e.issues_json, '[]')) je
                WHERE LOWER(CAST(je.value ->> 'label' AS VARCHAR)) = LOWER(?)
            )
            """
        )
        params.append(scope["issue_label"])

    return " AND ".join(where_clauses), params


def _fetch_kpi_snapshot(scope: dict[str, Any]) -> dict[str, Any]:
    where_sql, params = _build_filters(scope)
    query = f"""
        SELECT
            COUNT(*) AS total_reviews,
            AVG(COALESCE(r.score, 0)) AS avg_rating,
            AVG(CASE WHEN COALESCE(e.sentiment_label, '') = 'negative' THEN 1.0 ELSE 0.0 END) AS pct_negative,
            SUM(CASE WHEN COALESCE(e.severity_band, '') = 'critical' THEN 1 ELSE 0 END) AS critical_count
        FROM reviews_raw r
        JOIN reviews_enriched e USING (review_id)
        WHERE {where_sql}
    """
    with get_connection(read_only=True) as conn:
        total_reviews, avg_rating, pct_negative, critical_count = conn.execute(query, params).fetchone()

    return {
        "total_reviews": int(total_reviews or 0),
        "avg_rating": round(float(avg_rating or 0.0), 4),
        "pct_negative": round(float(pct_negative or 0.0), 4),
        "critical_count": int(critical_count or 0),
    }


def _fetch_top_issues(scope: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    where_sql, params = _build_filters(scope)
    query = f"""
        SELECT
            CAST(je.value ->> 'label' AS VARCHAR) AS label,
            COUNT(*) AS review_count,
            SUM(COALESCE(e.severity_score, 0.0)) AS weighted_severity
        FROM reviews_raw r
        JOIN reviews_enriched e USING (review_id),
             LATERAL json_each(COALESCE(e.issues_json, '[]')) je
        WHERE {where_sql}
          AND CAST(je.value ->> 'label' AS VARCHAR) IS NOT NULL
        GROUP BY 1
        ORDER BY weighted_severity DESC, review_count DESC, label
        LIMIT ?
    """
    with get_connection(read_only=True) as conn:
        rows = conn.execute(query, [*params, max(1, int(limit))]).fetchall()

    return [
        {
            "label": str(label),
            "review_count": int(review_count or 0),
            "weighted_severity": round(float(weighted_severity or 0.0), 3),
        }
        for label, review_count, weighted_severity in rows
    ]


def _fetch_anomaly_flags(scope: dict[str, Any]) -> list[dict[str, Any]]:
    if scope["category"] or scope["version"] or scope["issue_label"]:
        return []

    with get_connection(read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT anomaly_flags_json
            FROM daily_aggregates
            WHERE day >= ? AND day <= ?
            """,
            [scope["start_date"], scope["end_date"]],
        ).fetchall()

    anomalies: list[dict[str, Any]] = []
    for (payload,) in rows:
        try:
            items = json.loads(payload or "[]")
        except json.JSONDecodeError:
            items = []
        for item in items:
            if isinstance(item, dict):
                anomalies.append(item)
    return anomalies[:10]


def _fetch_evidence(scope: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    evidence = get_evidence_quotes(
        start_date=scope["start_date"],
        end_date=scope["end_date"],
        issue_label=scope["issue_label"] or None,
        version=scope["version"] or None,
        category=scope["category"] or None,
        limit=limit,
    )
    return evidence


def _compact_quote(text: str, max_chars: int = 120) -> str:
    clean = (text or "").strip().replace("\n", " ")
    if len(clean) <= max_chars:
        return clean
    return clean[:max_chars].rstrip() + "..."


def _load_prompt_sections(prompt_path: Path) -> tuple[str, str]:
    text = prompt_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    current = None
    system_lines: list[str] = []
    user_lines: list[str] = []

    for line in lines:
        marker = line.strip().lower()
        if marker == "## system":
            current = "system"
            continue
        if marker == "## user":
            current = "user"
            continue

        if current == "system":
            system_lines.append(line)
        elif current == "user":
            user_lines.append(line)

    system = "\n".join(system_lines).strip()
    user = "\n".join(user_lines).strip()
    if not system:
        system = "You are an analyst assistant. Return strict JSON only."
    if not user:
        user = text.strip()
    return system, user


def _build_input_payload(scope: dict[str, Any], report_type: str) -> dict[str, Any]:
    raw_evidence = _fetch_evidence(scope, limit=10)
    compact_evidence = [
        {
            "quote": _compact_quote(str(item.get("quote", ""))),
            "sentiment_label": item.get("sentiment_label"),
            "severity_score": item.get("severity_score"),
            "app_version": item.get("app_version"),
        }
        for item in raw_evidence
    ]

    payload = {
        "scope": scope,
        "kpi_snapshot": _fetch_kpi_snapshot(scope),
        "top_issues": _fetch_top_issues(scope, limit=5),
        "evidence_reviews": compact_evidence,
    }

    if report_type == "weekly_exec_brief":
        payload["anomaly_flags"] = _fetch_anomaly_flags(scope)[:5]

    return payload


def _weekly_driver_impact(weighted_severity: float) -> str:
    if weighted_severity >= 12.0:
        return "high"
    if weighted_severity >= 5.0:
        return "med"
    return "low"


def _build_weekly_exec_brief_fallback(input_payload: dict[str, Any]) -> dict[str, Any]:
    scope = input_payload.get("scope", {})
    kpi = input_payload.get("kpi_snapshot", {})
    top_issues = input_payload.get("top_issues", [])
    evidence = input_payload.get("evidence_reviews", [])

    week_range = f"{scope.get('start_date', '')}..{scope.get('end_date', '')}"
    avg_rating = float(kpi.get("avg_rating", 0.0) or 0.0)
    pct_negative = float(kpi.get("pct_negative", 0.0) or 0.0)
    critical_count = int(kpi.get("critical_count", 0) or 0)

    headline = (
        f"Weekly health: rating {avg_rating:.2f}, negative {pct_negative:.1%}, "
        f"critical {critical_count}."
    )

    evidence_quotes = [str(item.get("quote", "")) for item in evidence if item.get("quote")]

    drivers = []
    for issue in top_issues[:2]:
        label = str(issue.get("label", "Unknown Issue"))
        drivers.append(
            {
                "title": label,
                "impact": _weekly_driver_impact(float(issue.get("weighted_severity", 0.0) or 0.0)),
                "evidence_quotes": evidence_quotes[:2],
            }
        )

    risks = []
    if pct_negative >= 0.35:
        risks.append(
            {
                "risk": "Negative sentiment remains elevated",
                "signal": f"pct_negative={pct_negative:.1%}",
                "severity": "high",
            }
        )
    if critical_count >= 8:
        risks.append(
            {
                "risk": "Critical incidents may impact retention",
                "signal": f"critical_count={critical_count}",
                "severity": "med",
            }
        )
    while len(risks) < 2:
        risks.append(
            {
                "risk": "Issue concentration may reduce trust",
                "signal": "Top issues concentrated in a few themes",
                "severity": "low",
            }
        )

    recommendations = [
        {
            "action": "Prioritize fixes for top severity drivers in next sprint",
            "owner": "Eng",
            "expected_impact": "Reduce negative sentiment and critical volume",
        },
        {
            "action": "Publish known-issues guidance for affected users",
            "owner": "Support",
            "expected_impact": "Lower ticket friction and improve user confidence",
        },
        {
            "action": "Align roadmap updates with highest-frequency complaints",
            "owner": "PM",
            "expected_impact": "Improve rating trajectory and perceived responsiveness",
        },
    ]

    return {
        "week_range": week_range,
        "headline": headline,
        "kpi_summary": {
            "avg_rating": avg_rating,
            "pct_negative": pct_negative,
            "critical_count": critical_count,
        },
        "drivers": drivers,
        "risks": risks[:2],
        "recommendations": recommendations[:3],
    }


def _generate_report(
    report_type: str,
    prompt_file: str,
    schema_file: str,
    scope: dict[str, Any],
) -> dict[str, Any]:
    normalized_scope = _normalize_scope(scope)
    prompt_path = PROMPTS_DIR / prompt_file
    schema_path = SCHEMAS_DIR / schema_file

    schema = load_json_schema(schema_path)
    schema_validator = build_jsonschema_validator(schema)
    system_prompt, user_prompt_template = _load_prompt_sections(prompt_path)

    input_payload = _build_input_payload(normalized_scope, report_type=report_type)
    input_json = json.dumps(input_payload, indent=2, ensure_ascii=True)
    user_prompt = user_prompt_template.replace("{{input_json}}", input_json)

    def _generator() -> dict[str, Any]:
        try:
            return call_json_with_retry(
                model=DEFAULT_MODEL,
                system=system_prompt,
                user=user_prompt,
                schema_validator=schema_validator,
                max_retries=1,
            )
        except Exception:  # noqa: BLE001
            if report_type == "weekly_exec_brief":
                fallback = _build_weekly_exec_brief_fallback(input_payload)
                schema_validator(fallback)
                return fallback
            raise

    return get_or_create_report(
        report_type=report_type,
        scope=normalized_scope,
        model=DEFAULT_MODEL,
        generator=_generator,
    )


def generate_weekly_exec_brief(scope: dict[str, Any]) -> dict[str, Any]:
    return _generate_report(
        report_type="weekly_exec_brief",
        prompt_file="weekly_exec_brief.md",
        schema_file="weekly_exec_brief.schema.json",
        scope=scope,
    )


def generate_sprint_backlog(scope: dict[str, Any]) -> dict[str, Any]:
    return _generate_report(
        report_type="sprint_backlog",
        prompt_file="sprint_backlog.md",
        schema_file="sprint_backlog.schema.json",
        scope=scope,
    )
