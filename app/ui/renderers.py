from __future__ import annotations

import html
import json
import tempfile
from collections import defaultdict
from typing import Any

import pandas as pd

PRIORITY_ORDER = ["P0", "P1", "P2", "P3"]


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_payload(backlog_json: str | dict[str, Any] | None) -> dict[str, Any]:
    if backlog_json is None:
        return {"tickets": []}
    if isinstance(backlog_json, dict):
        return backlog_json
    if isinstance(backlog_json, str):
        clean = backlog_json.strip()
        if not clean:
            return {"tickets": []}
        try:
            parsed = json.loads(clean)
            return parsed if isinstance(parsed, dict) else {"tickets": []}
        except json.JSONDecodeError:
            return {
                "error": "invalid_json",
                "message": "Sprint backlog payload is not valid JSON.",
                "tickets": [],
            }
    return {"tickets": []}


def _first_non_empty(ticket: dict[str, Any], keys: list[str], default: str = "") -> str:
    for key in keys:
        value = ticket.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _ticket_rows(tickets: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for idx, ticket in enumerate(tickets, start=1):
        rows.append(
            {
                "ticket_id": idx,
                "priority": str(ticket.get("priority", "P3")),
                "title": str(ticket.get("title", "Untitled")),
                "type": str(ticket.get("type", "")),
                "severity_score": _to_float(ticket.get("severity_score")),
                "owner": _first_non_empty(ticket, ["suggested_owner", "owner", "assignee"], default="Unassigned"),
                "due_date": _first_non_empty(ticket, ["due_date", "target_date", "eta"], default=""),
                "related_labels": ", ".join(ticket.get("related_labels", []) or []),
                "related_versions": ", ".join(ticket.get("related_versions", []) or []),
                "impact_notes": str(ticket.get("impact_notes", "")),
            }
        )
    return pd.DataFrame(rows)


def _export_csv(df: pd.DataFrame) -> str | None:
    if df.empty:
        return None
    tmp = tempfile.NamedTemporaryFile(prefix="sprint_backlog_", suffix=".csv", delete=False, mode="w", encoding="utf-8")
    df.to_csv(tmp.name, index=False)
    tmp.flush()
    tmp.close()
    return tmp.name


def _badge(label: str, value: str, tone: str = "neutral") -> str:
    safe_label = html.escape(label)
    safe_value = html.escape(value) if value else "-"
    return f"<span class='ri-badge ri-badge-{tone}'>{safe_label}: {safe_value}</span>"


def _render_ticket_card(ticket: dict[str, Any], index: int) -> str:
    title = html.escape(str(ticket.get("title", "Untitled ticket")))
    description = html.escape(str(ticket.get("impact_notes", "No description provided.")))
    ticket_type = str(ticket.get("type", "")).upper() or "TASK"
    priority = html.escape(str(ticket.get("priority", "P3")))
    severity = f"{_to_float(ticket.get('severity_score')):.2f}"
    owner = _first_non_empty(ticket, ["suggested_owner", "owner", "assignee"], default="Unassigned")
    due_date = _first_non_empty(ticket, ["due_date", "target_date", "eta"], default="No due date")

    confidence = _first_non_empty(ticket, ["confidence", "confidence_level"], default="n/a")
    issue_category = _first_non_empty(ticket, ["issue_category", "category", "type"], default="n/a")
    component = _first_non_empty(ticket, ["component", "module", "area"], default="n/a")

    acceptance_criteria = ticket.get("acceptance_criteria", []) or []
    evidence_quotes = ticket.get("evidence_quotes", []) or []

    criteria_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in acceptance_criteria) or "<li>Not provided</li>"
    evidence_html = "".join(f"<blockquote>{html.escape(str(item))}</blockquote>" for item in evidence_quotes) or "<p>No evidence quotes.</p>"

    badges = "".join(
        [
            _badge("Category", issue_category, tone="neutral"),
            _badge("Component", component, tone="neutral"),
            _badge("Severity", severity, tone="warn"),
            _badge("Confidence", confidence, tone="info"),
        ]
    )

    return f"""
    <article class="ri-ticket-card">
      <header class="ri-ticket-header">
        <div>
          <div class="ri-ticket-meta">#{index} · {priority} · {html.escape(ticket_type)}</div>
          <h4>{title}</h4>
        </div>
        <div class="ri-ticket-owner">{html.escape(owner)}</div>
      </header>
      <div class="ri-ticket-chips">
        <span class="ri-chip">Due: {html.escape(due_date)}</span>
      </div>
      <div class="ri-ticket-badges">{badges}</div>
      <details>
        <summary>Description</summary>
        <p>{description}</p>
      </details>
      <details>
        <summary>Acceptance Criteria</summary>
        <ul>{criteria_html}</ul>
      </details>
      <details>
        <summary>Evidence Quotes</summary>
        {evidence_html}
      </details>
    </article>
    """


def _render_board(payload: dict[str, Any], tickets: list[dict[str, Any]], summary_df: pd.DataFrame) -> str:
    total = len(tickets)
    p0_count = int((summary_df["priority"] == "P0").sum()) if not summary_df.empty else 0
    p1_count = int((summary_df["priority"] == "P1").sum()) if not summary_df.empty else 0
    risk_flags = int((summary_df["severity_score"] >= 0.75).sum()) if not summary_df.empty else 0

    effort_fields = ["estimated_effort", "effort", "story_points", "estimate"]
    est_effort = 0.0
    has_effort = False
    for ticket in tickets:
        for field in effort_fields:
            if field in ticket:
                est_effort += _to_float(ticket.get(field))
                has_effort = True
                break

    effort_display = f"{est_effort:.1f}" if has_effort else "0.0"

    kpi_html = f"""
    <section class="ri-board-kpis">
      <div class="ri-kpi"><span>Total Tickets</span><strong>{total}</strong></div>
      <div class="ri-kpi"><span>P0 / P1</span><strong>{p0_count} / {p1_count}</strong></div>
      <div class="ri-kpi"><span>Estimated Effort</span><strong>{effort_display}</strong></div>
      <div class="ri-kpi"><span>Risk Flags</span><strong>{risk_flags}</strong></div>
    </section>
    """

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ticket in tickets:
        grouped[str(ticket.get("priority", "P3"))].append(ticket)

    sections = []
    ticket_index = 1
    for priority in PRIORITY_ORDER:
        chunk = grouped.get(priority, [])
        if not chunk:
            continue
        cards_html = []
        for ticket in chunk:
            cards_html.append(_render_ticket_card(ticket, ticket_index))
            ticket_index += 1
        sections.append(
            f"""
            <section class="ri-priority-group">
              <h3>{html.escape(priority)} <span>{len(chunk)} tickets</span></h3>
              <div class="ri-ticket-grid">{''.join(cards_html)}</div>
            </section>
            """
        )

    error_block = ""
    if payload.get("error"):
        error_block = (
            "<div class='ri-board-error'>"
            f"{html.escape(str(payload.get('message', 'Backlog generation error.')))}"
            "</div>"
        )

    if not sections:
        sections.append("<div class='ri-empty'>No backlog tickets were returned for this scope.</div>")

    return f"<div class='ri-ticket-board'>{error_block}{kpi_html}{''.join(sections)}</div>"


def render_sprint_backlog(backlog_json: str | dict[str, Any] | None) -> tuple[str, dict[str, Any], str | None, pd.DataFrame]:
    payload = _normalize_payload(backlog_json)
    raw_tickets = payload.get("tickets", [])
    tickets = [item for item in raw_tickets if isinstance(item, dict)]

    summary_df = _ticket_rows(tickets)
    board_html = _render_board(payload, tickets, summary_df)
    csv_file = _export_csv(summary_df)

    if payload.get("error") and not tickets:
        return board_html, payload, csv_file, pd.DataFrame(columns=["message"])

    return board_html, payload, csv_file, summary_df


def _exec_kpi_table(payload: dict[str, Any]) -> pd.DataFrame:
    kpi = payload.get("kpi_summary", {}) if isinstance(payload.get("kpi_summary"), dict) else {}
    avg_rating = _to_float(kpi.get("avg_rating"))
    pct_negative = _to_float(kpi.get("pct_negative")) * 100
    critical = int(_to_float(kpi.get("critical_count")))
    return pd.DataFrame(
        [
            {"metric": "avg_rating", "value": round(avg_rating, 3)},
            {"metric": "pct_negative", "value": f"{pct_negative:.1f}%"},
            {"metric": "critical_count", "value": critical},
        ]
    )


def render_exec_brief(exec_json: str | dict[str, Any] | None) -> tuple[str, dict[str, Any], pd.DataFrame]:
    payload = _normalize_payload(exec_json)
    if "kpi_summary" not in payload:
        payload = payload or {}
        payload.setdefault("kpi_summary", {})
        payload.setdefault("drivers", [])
        payload.setdefault("risks", [])
        payload.setdefault("recommendations", [])

    week_range = html.escape(str(payload.get("week_range", "n/a")))
    headline = html.escape(str(payload.get("headline", "No executive headline available.")))

    kpi_df = _exec_kpi_table(payload)
    avg_rating = kpi_df.loc[kpi_df["metric"] == "avg_rating", "value"].iloc[0] if not kpi_df.empty else 0.0
    pct_negative = kpi_df.loc[kpi_df["metric"] == "pct_negative", "value"].iloc[0] if not kpi_df.empty else "0.0%"
    critical = kpi_df.loc[kpi_df["metric"] == "critical_count", "value"].iloc[0] if not kpi_df.empty else 0

    drivers_blocks = []
    for idx, driver in enumerate(payload.get("drivers", []), start=1):
        if not isinstance(driver, dict):
            continue
        title = html.escape(str(driver.get("title", "Driver")))
        impact = html.escape(str(driver.get("impact", "low")).upper())
        quotes = driver.get("evidence_quotes", []) or []
        quotes_html = "".join(f"<li>{html.escape(str(q))}</li>" for q in quotes) or "<li>No supporting quotes provided.</li>"
        drivers_blocks.append(
            f"""
            <div class="ri-exec-item">
              <h4>{idx}. {title} <span class="ri-inline-pill">Impact: {impact}</span></h4>
              <ul>{quotes_html}</ul>
            </div>
            """
        )

    risks_items = []
    for risk in payload.get("risks", []):
        if not isinstance(risk, dict):
            continue
        risk_text = html.escape(str(risk.get("risk", "Risk")))
        signal_text = html.escape(str(risk.get("signal", "n/a")))
        severity = html.escape(str(risk.get("severity", "low")).upper())
        risks_items.append(f"<li><strong>{risk_text}</strong> ({severity}) - {signal_text}</li>")

    rec_items = []
    for rec in payload.get("recommendations", []):
        if not isinstance(rec, dict):
            continue
        action = html.escape(str(rec.get("action", "Recommendation")))
        owner = html.escape(str(rec.get("owner", "n/a")))
        impact = html.escape(str(rec.get("expected_impact", "")))
        rec_items.append(f"<li><strong>{action}</strong> <em>[Owner: {owner}]</em>. {impact}</li>")

    brief_html = f"""
    <article class="ri-exec-prose">
      <header class="ri-exec-header">
        <p class="ri-exec-week">Week: {week_range}</p>
        <h2>{headline}</h2>
        <p class="ri-exec-summary">
          During this period, average rating was <strong>{avg_rating}</strong>, negative sentiment was
          <strong>{pct_negative}</strong>, and critical review count was <strong>{critical}</strong>.
        </p>
      </header>

      <section>
        <h3>Primary Drivers</h3>
        {''.join(drivers_blocks) if drivers_blocks else "<p>No drivers available.</p>"}
      </section>

      <section>
        <h3>Risk Outlook</h3>
        <ul>{''.join(risks_items) if risks_items else "<li>No explicit risks provided.</li>"}</ul>
      </section>

      <section>
        <h3>Recommended Actions</h3>
        <ol>{''.join(rec_items) if rec_items else "<li>No recommendations provided.</li>"}</ol>
      </section>
    </article>
    """
    return brief_html, payload, kpi_df
