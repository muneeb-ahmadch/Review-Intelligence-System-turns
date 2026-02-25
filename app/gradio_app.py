from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import gradio as gr
import pandas as pd

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from analytics.evidence_quotes import get_evidence_quotes
from app.config import DUCKDB_PATH
from app.services.insights_service import generate_sprint_backlog, generate_weekly_exec_brief
from app.services.search_service import get_filter_options, search_reviews
from app.ui.components import (
    build_exec_brief_page,
    build_issues_page,
    build_overview_page,
    build_release_diff_page,
    build_sprint_planner_page,
    build_trends_page,
)
from app.ui.plots import (
    get_daily_trends,
    plot_critical_count_trend,
    plot_pct_negative_trend,
    plot_rating_trend,
)
from app.ui.renderers import render_exec_brief, render_sprint_backlog
from app.ui.theme import build_theme, load_css


def _to_date_string(value: str | date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if "T" in text:
            return text.split("T", 1)[0]
        if " " in text:
            return text.split(" ", 1)[0]
        return text
    return None


def _safe_pct(value: float | None) -> str:
    if value is None:
        return "0.0%"
    return f"{value * 100:.1f}%"


def _get_kpis(start_date: str | None, end_date: str | None) -> dict[str, Any]:
    query = """
        SELECT
            SUM(total_reviews) AS total_reviews,
            SUM(avg_rating * total_reviews) / NULLIF(SUM(total_reviews), 0) AS avg_rating,
            SUM(pct_negative * total_reviews) / NULLIF(SUM(total_reviews), 0) AS pct_negative,
            SUM(critical_count) AS critical_count,
            SUM(churn_high_users) AS churn_high_users
        FROM daily_aggregates
        WHERE day >= ? AND day <= ?
    """

    with duckdb.connect(str(DUCKDB_PATH), read_only=True) as conn:
        total_reviews, avg_rating, pct_negative, critical_count, churn_high_users = conn.execute(
            query, [start_date, end_date]
        ).fetchone()

    return {
        "total_reviews": int(total_reviews or 0),
        "avg_rating": float(avg_rating or 0.0),
        "pct_negative": float(pct_negative or 0.0),
        "critical_count": int(critical_count or 0),
        "churn_high_users": int(churn_high_users or 0),
    }


def _get_top_issues(start_date: str | None, end_date: str | None, top_n: int = 5) -> pd.DataFrame:
    query = """
        SELECT top_issues_json
        FROM daily_aggregates
        WHERE day >= ? AND day <= ?
    """

    with duckdb.connect(str(DUCKDB_PATH), read_only=True) as conn:
        rows = conn.execute(query, [start_date, end_date]).fetchall()

    bucket: dict[str, dict[str, float]] = {}
    for (payload,) in rows:
        try:
            items = json.loads(payload or "[]")
        except json.JSONDecodeError:
            items = []
        for issue in items:
            label = str(issue.get("label", "Unknown"))
            bucket.setdefault(label, {"review_count": 0.0, "weighted_severity": 0.0})
            bucket[label]["review_count"] += float(issue.get("review_count", 0.0) or 0.0)
            bucket[label]["weighted_severity"] += float(issue.get("weighted_severity", 0.0) or 0.0)

    if not bucket:
        return pd.DataFrame(columns=["issue_label", "review_count", "weighted_severity"])

    rows_out = [
        {
            "issue_label": label,
            "review_count": int(values["review_count"]),
            "weighted_severity": round(values["weighted_severity"], 3),
        }
        for label, values in bucket.items()
    ]
    df = pd.DataFrame(rows_out).sort_values(
        ["weighted_severity", "review_count", "issue_label"], ascending=[False, False, True]
    )
    return df.head(top_n).reset_index(drop=True)


def _format_quotes(quotes: list[dict[str, Any]]) -> str:
    if not quotes:
        return "No evidence quotes found for current filters."

    lines = []
    for idx, q in enumerate(quotes, start=1):
        lines.append(
            (
                f"{idx}. {q['quote']}\n"
                f"   - `{q['day']}` | v`{q['app_version']}` | {q['category_taxonomy']} | "
                f"sentiment: {q['sentiment_label']} | severity: {q['severity_score']}"
            )
        )
    return "\n\n".join(lines)


def _default_range(min_day: str | None, max_day: str | None) -> tuple[str, str]:
    if not min_day or not max_day:
        today = date.today()
        return ((today - timedelta(days=6)).isoformat(), today.isoformat())

    end = datetime.fromisoformat(max_day).date()
    start = max(datetime.fromisoformat(min_day).date(), end - timedelta(days=6))
    return (start.isoformat(), end.isoformat())


def _resolve_preset_range(preset: str, min_day: str | None, max_day: str | None) -> tuple[str, str]:
    data_end = datetime.fromisoformat(max_day).date() if max_day else date.today()
    data_min = datetime.fromisoformat(min_day).date() if min_day else None

    if preset == "YTD":
        start = date(data_end.year, 1, 1)
    else:
        days_map = {"7D": 7, "30D": 30, "90D": 90}
        days = days_map.get(preset, 7)
        start = data_end - timedelta(days=days - 1)

    if data_min and start < data_min:
        start = data_min
    return start.isoformat(), data_end.isoformat()


def _runtime_status(db_ready: bool) -> str:
    if not db_ready:
        return "DB not connected"

    try:
        with duckdb.connect(str(DUCKDB_PATH), read_only=True) as conn:
            last_day = conn.execute("SELECT MAX(day) FROM daily_aggregates").fetchone()[0]
    except Exception:  # noqa: BLE001
        last_day = None

    if last_day:
        return f"DB connected · Last pipeline day: {last_day}"
    return "DB connected"


def _overview_payload(start_date: str, end_date: str):
    start = _to_date_string(start_date)
    end = _to_date_string(end_date)
    if not start or not end:
        return (
            "Avg Rating: n/a",
            "% Negative: n/a",
            "Critical Count: n/a",
            "Churn High Users: n/a",
            pd.DataFrame(),
            None,
            None,
            None,
            "Please provide both start and end dates.",
        )

    kpis = _get_kpis(start, end)
    trends_df = get_daily_trends(start, end)
    top_issues_df = _get_top_issues(start, end, top_n=5)

    rating_fig = plot_rating_trend(trends_df)
    pct_neg_fig = plot_pct_negative_trend(trends_df)
    critical_fig = plot_critical_count_trend(trends_df)

    summary = (
        f"Window: `{start}` to `{end}` | Reviews: **{kpis['total_reviews']}** | "
        f"Rows in trend: **{len(trends_df)}**"
    )

    return (
        f"**{kpis['avg_rating']:.2f}**\nAvg Rating",
        f"**{_safe_pct(kpis['pct_negative'])}**\n% Negative",
        f"**{kpis['critical_count']}**\nCritical Count",
        f"**{kpis['churn_high_users']}**\nChurn High Users",
        top_issues_df,
        rating_fig,
        pct_neg_fig,
        critical_fig,
        summary,
    )


def _drilldown_payload(
    start_date: str,
    end_date: str,
    category: str | None,
    issue_label: str | None,
    version: str | None,
    page: int,
    page_size: int,
):
    start = _to_date_string(start_date)
    end = _to_date_string(end_date)

    rows_df, total_count = search_reviews(
        start_date=start,
        end_date=end,
        category=category or None,
        issue_label=issue_label or None,
        version=version or None,
        page=page,
        page_size=page_size,
    )

    quotes = get_evidence_quotes(
        start_date=start,
        end_date=end,
        issue_label=issue_label or None,
        version=version or None,
        category=category or None,
        limit=8,
    )

    total_pages = max(1, (total_count + max(page_size, 1) - 1) // max(page_size, 1))
    page = min(max(page, 1), total_pages)
    status = f"Showing page {page}/{total_pages} | page_size={page_size} | total_rows={total_count}"

    return rows_df, _format_quotes(quotes), status


def _release_delta(version_a: str | None, version_b: str | None) -> pd.DataFrame:
    if not version_a or not version_b:
        return pd.DataFrame(columns=["metric", "version_a", "version_b", "delta_b_minus_a"])

    with duckdb.connect(str(DUCKDB_PATH), read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT app_version, avg_rating, pct_negative, critical_count
            FROM version_aggregates
            WHERE app_version IN (?, ?)
            """,
            [version_a, version_b],
        ).fetchall()

    data = {row[0]: row[1:] for row in rows}
    if version_a not in data or version_b not in data:
        return pd.DataFrame(columns=["metric", "version_a", "version_b", "delta_b_minus_a"])

    a_avg, a_neg, a_crit = data[version_a]
    b_avg, b_neg, b_crit = data[version_b]

    out_rows = [
        {
            "metric": "avg_rating",
            "version_a": round(float(a_avg or 0.0), 3),
            "version_b": round(float(b_avg or 0.0), 3),
            "delta_b_minus_a": round(float((b_avg or 0.0) - (a_avg or 0.0)), 3),
        },
        {
            "metric": "pct_negative",
            "version_a": round(float(a_neg or 0.0), 4),
            "version_b": round(float(b_neg or 0.0), 4),
            "delta_b_minus_a": round(float((b_neg or 0.0) - (a_neg or 0.0)), 4),
        },
        {
            "metric": "critical_count",
            "version_a": int(a_crit or 0),
            "version_b": int(b_crit or 0),
            "delta_b_minus_a": int((b_crit or 0) - (a_crit or 0)),
        },
    ]
    return pd.DataFrame(out_rows)


def _write_download_json(payload: dict[str, Any], prefix: str) -> str:
    tmp = tempfile.NamedTemporaryFile(prefix=f"{prefix}_", suffix=".json", delete=False, mode="w", encoding="utf-8")
    json.dump(payload, tmp, indent=2, ensure_ascii=True)
    tmp.flush()
    tmp.close()
    return tmp.name


def _generate_exec_brief_payload(
    start_date: str,
    end_date: str,
    category: str | None,
    version: str | None,
    issue_label: str | None,
):
    scope = {
        "start_date": _to_date_string(start_date),
        "end_date": _to_date_string(end_date),
        "category": category or "",
        "version": version or "",
        "issue_label": issue_label or "",
    }
    try:
        report = generate_weekly_exec_brief(scope)
        board_html, raw_payload, kpi_df = render_exec_brief(report)
        return board_html, raw_payload, kpi_df, _write_download_json(report, "weekly_exec_brief")
    except Exception as exc:  # noqa: BLE001
        error_payload = {
            "error": "exec_brief_generation_failed",
            "message": str(exc),
        }
        board_html, raw_payload, kpi_df = render_exec_brief(error_payload)
        return board_html, raw_payload, kpi_df, None


def _generate_sprint_backlog_payload(
    start_date: str,
    end_date: str,
    category: str | None,
    version: str | None,
    issue_label: str | None,
):
    scope = {
        "start_date": _to_date_string(start_date),
        "end_date": _to_date_string(end_date),
        "category": category or "",
        "version": version or "",
        "issue_label": issue_label or "",
    }
    try:
        report = generate_sprint_backlog(scope)
        board_html, raw_payload, csv_file, summary_df = render_sprint_backlog(report)
        return board_html, raw_payload, summary_df, csv_file, _write_download_json(report, "sprint_backlog")
    except Exception as exc:  # noqa: BLE001
        error_payload = {
            "error": "sprint_backlog_generation_failed",
            "message": str(exc),
            "tickets": [],
        }
        board_html, raw_payload, csv_file, summary_df = render_sprint_backlog(error_payload)
        return board_html, raw_payload, summary_df, csv_file, None


def _route_page(active: str):
    pages = [
        ("overview", "Overview"),
        ("trends", "Trends & Anomalies"),
        ("issues", "Issues Drilldown"),
        ("release", "Release Diff"),
        ("exec", "Executive Brief"),
        ("sprint", "Sprint Planner"),
    ]
    title = next((name for key, name in pages if key == active), "Overview")

    button_updates = [
        gr.update(variant="primary" if key == active else "secondary")
        for key, _ in pages
    ]
    page_updates = [gr.update(visible=(key == active)) for key, _ in pages]

    return [f"### {title}", active, *button_updates, *page_updates]


def _bind_preset_buttons(date_controls: dict[str, Any], min_day: str | None, max_day: str | None) -> None:
    def _preset_handler(preset: str):
        return _resolve_preset_range(preset, min_day=min_day, max_day=max_day)

    date_controls["preset_7d"].click(
        fn=lambda: _preset_handler("7D"),
        inputs=None,
        outputs=[date_controls["start"], date_controls["end"]],
    )
    date_controls["preset_30d"].click(
        fn=lambda: _preset_handler("30D"),
        inputs=None,
        outputs=[date_controls["start"], date_controls["end"]],
    )
    date_controls["preset_90d"].click(
        fn=lambda: _preset_handler("90D"),
        inputs=None,
        outputs=[date_controls["start"], date_controls["end"]],
    )
    date_controls["preset_ytd"].click(
        fn=lambda: _preset_handler("YTD"),
        inputs=None,
        outputs=[date_controls["start"], date_controls["end"]],
    )


def build_app() -> gr.Blocks:
    db_ready = DUCKDB_PATH.exists()
    filters = get_filter_options() if db_ready else {}

    min_day = filters.get("min_day")
    max_day = filters.get("max_day")
    default_start, default_end = _default_range(min_day, max_day)

    categories = [""] + filters.get("categories", [])
    issue_labels = [""] + filters.get("issue_labels", [])
    versions = filters.get("versions", [])

    version_a_default = versions[0] if versions else None
    version_b_default = versions[1] if len(versions) > 1 else version_a_default

    css_path = Path(__file__).resolve().parent / "ui" / "styles.css"

    with gr.Blocks(
        title="Review Intelligence Dashboard",
        theme=build_theme(),
        css=load_css(css_path),
    ) as demo:
        current_page = gr.State("overview")

        with gr.Row(elem_classes=["ri-dashboard"]):
            with gr.Column(scale=2, elem_classes=["ri-sidebar"]):
                gr.Markdown("<div class='ri-sidebar-title'>Navigation</div>")
                btn_overview = gr.Button("Overview", variant="primary")
                btn_trends = gr.Button("Trends")
                btn_issues = gr.Button("Issues")
                btn_release = gr.Button("Release Diff")
                btn_exec = gr.Button("Executive Brief")
                btn_sprint = gr.Button("Sprint Planner")

            with gr.Column(scale=8, elem_classes=["ri-main"]):
                with gr.Group(elem_classes=["ri-topbar"]):
                    with gr.Row(equal_height=True):
                        gr.Markdown(
                            """
                            <div class="ri-app-title">Review Intelligence</div>
                            <div class="ri-active-title">Product-grade dashboard for review analytics</div>
                            """
                        )
                        gr.Markdown(f"<div class='ri-status-pill'>{_runtime_status(db_ready)}</div>")
                    active_page_title = gr.Markdown("### Overview")

                overview = build_overview_page(default_start=default_start, default_end=default_end)
                trends = build_trends_page()
                issues = build_issues_page(
                    default_start=default_start,
                    default_end=default_end,
                    categories=categories,
                    issue_labels=issue_labels,
                    versions=versions,
                )
                release = build_release_diff_page(
                    versions=versions,
                    version_a_default=version_a_default,
                    version_b_default=version_b_default,
                )
                exec_brief = build_exec_brief_page(
                    default_start=default_start,
                    default_end=default_end,
                    categories=categories,
                    issue_labels=issue_labels,
                    versions=versions,
                )
                sprint = build_sprint_planner_page(
                    default_start=default_start,
                    default_end=default_end,
                    categories=categories,
                    issue_labels=issue_labels,
                    versions=versions,
                )

        nav_buttons = [btn_overview, btn_trends, btn_issues, btn_release, btn_exec, btn_sprint]
        page_containers = [
            overview["page"],
            trends["page"],
            issues["container"],
            release["page"],
            exec_brief["page"],
            sprint["page"],
        ]

        for button, page_key in zip(
            nav_buttons,
            ["overview", "trends", "issues", "release", "exec", "sprint"],
            strict=True,
        ):
            button.click(
                fn=lambda key=page_key: _route_page(key),
                inputs=None,
                outputs=[active_page_title, current_page, *nav_buttons, *page_containers],
            )

        _bind_preset_buttons(overview["date"], min_day=min_day, max_day=max_day)
        _bind_preset_buttons(issues["date"], min_day=min_day, max_day=max_day)
        _bind_preset_buttons(exec_brief["date"], min_day=min_day, max_day=max_day)
        _bind_preset_buttons(sprint["date"], min_day=min_day, max_day=max_day)

        overview["refresh"].click(
            fn=_overview_payload,
            inputs=[overview["date"]["start"], overview["date"]["end"]],
            outputs=[
                overview["kpi_avg_rating"],
                overview["kpi_pct_negative"],
                overview["kpi_critical"],
                overview["kpi_churn"],
                overview["top_issues"],
                overview["rating_plot"],
                overview["pct_negative_plot"],
                overview["critical_plot"],
                overview["summary"],
            ],
        )

        issues["run"].click(
            fn=_drilldown_payload,
            inputs=[
                issues["date"]["start"],
                issues["date"]["end"],
                issues["category"],
                issues["issue"],
                issues["version"],
                issues["page_number"],
                issues["page_size"],
            ],
            outputs=[issues["table"], issues["quotes"], issues["status"]],
        )

        release["compare"].click(
            fn=_release_delta,
            inputs=[release["version_a"], release["version_b"]],
            outputs=[release["table"]],
        )

        exec_brief["generate"].click(
            fn=_generate_exec_brief_payload,
            inputs=[
                exec_brief["date"]["start"],
                exec_brief["date"]["end"],
                exec_brief["category"],
                exec_brief["version"],
                exec_brief["issue"],
            ],
            outputs=[exec_brief["board"], exec_brief["raw"], exec_brief["kpi_table"], exec_brief["download"]],
        )

        sprint["generate"].click(
            fn=_generate_sprint_backlog_payload,
            inputs=[
                sprint["date"]["start"],
                sprint["date"]["end"],
                sprint["category"],
                sprint["version"],
                sprint["issue"],
            ],
            outputs=[
                sprint["board"],
                sprint["raw"],
                sprint["summary"],
                sprint["csv_download"],
                sprint["json_download"],
            ],
        )

        demo.load(
            fn=_overview_payload,
            inputs=[overview["date"]["start"], overview["date"]["end"]],
            outputs=[
                overview["kpi_avg_rating"],
                overview["kpi_pct_negative"],
                overview["kpi_critical"],
                overview["kpi_churn"],
                overview["top_issues"],
                overview["rating_plot"],
                overview["pct_negative_plot"],
                overview["critical_plot"],
                overview["summary"],
            ],
        )

    return demo


def main() -> None:
    app = build_app()
    server_port = int(os.getenv("GRADIO_SERVER_PORT", "7861"))
    app.launch(server_name="127.0.0.1", server_port=server_port)


if __name__ == "__main__":
    main()
