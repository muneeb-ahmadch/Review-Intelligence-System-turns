from __future__ import annotations

from typing import Any

import gradio as gr
import pandas as pd


def _date_input(label: str, value: str, elem_id: str):
    datetime_cls = getattr(gr, "DateTime", None)
    if datetime_cls is not None:
        return datetime_cls(
            label=label,
            value=value,
            include_time=False,
            type="datetime",
            elem_classes=["ri-date-input"],
            elem_id=elem_id,
        )

    date_cls = getattr(gr, "Date", None)
    if date_cls is not None:
        return date_cls(
            label=label,
            value=value,
            type="string",
            elem_classes=["ri-date-input"],
            elem_id=elem_id,
        )

    return gr.Textbox(label=f"{label} (YYYY-MM-DD)", value=value, elem_id=elem_id)


def build_section_header(title: str, subtitle: str = "") -> None:
    gr.Markdown(
        f"""
        <div class="ri-section-title">{title}</div>
        <div class="ri-section-subtitle">{subtitle}</div>
        """,
        elem_classes=["ri-section-header"],
    )


def build_date_controls(prefix: str, default_start: str, default_end: str) -> dict[str, gr.components.Component]:
    with gr.Group(elem_classes=["ri-card", "ri-date-card"]):
        with gr.Row(equal_height=True):
            start = _date_input("Start Date", default_start, f"{prefix}_start")
            end = _date_input("End Date", default_end, f"{prefix}_end")
        with gr.Row(elem_classes=["ri-presets"]):
            preset_7d = gr.Button("7D", size="sm", elem_classes=["ri-preset-btn"])
            preset_30d = gr.Button("30D", size="sm", elem_classes=["ri-preset-btn"])
            preset_90d = gr.Button("90D", size="sm", elem_classes=["ri-preset-btn"])
            preset_ytd = gr.Button("YTD", size="sm", elem_classes=["ri-preset-btn"])

    return {
        "start": start,
        "end": end,
        "preset_7d": preset_7d,
        "preset_30d": preset_30d,
        "preset_90d": preset_90d,
        "preset_ytd": preset_ytd,
    }


def build_overview_page(default_start: str, default_end: str) -> dict[str, Any]:
    with gr.Column(visible=True, elem_classes=["ri-page"], elem_id="page_overview") as page:
        build_section_header("Overview", "Core KPIs, trends, and top weighted issues")
        date_controls = build_date_controls("overview", default_start, default_end)

        with gr.Row(elem_classes=["ri-kpi-grid"]):
            kpi_avg_rating = gr.Markdown(elem_classes=["ri-kpi-card"])
            kpi_pct_negative = gr.Markdown(elem_classes=["ri-kpi-card"])
            kpi_critical = gr.Markdown(elem_classes=["ri-kpi-card"])
            kpi_churn = gr.Markdown(elem_classes=["ri-kpi-card"])

        with gr.Row():
            ov_refresh = gr.Button("Refresh Overview", variant="primary")
        ov_summary = gr.Markdown(elem_classes=["ri-muted-text"])

        with gr.Row(elem_classes=["ri-chart-grid"]):
            rating_plot = gr.Plot(label="Rating Trend", elem_classes=["ri-card"])
            pct_negative_plot = gr.Plot(label="% Negative Trend", elem_classes=["ri-card"])
            critical_plot = gr.Plot(label="Critical Count Trend", elem_classes=["ri-card"])

        with gr.Group(elem_classes=["ri-card"]):
            ov_top_issues = gr.Dataframe(label="Top Issues (Weighted)", interactive=False)

    return {
        "page": page,
        "date": date_controls,
        "refresh": ov_refresh,
        "kpi_avg_rating": kpi_avg_rating,
        "kpi_pct_negative": kpi_pct_negative,
        "kpi_critical": kpi_critical,
        "kpi_churn": kpi_churn,
        "summary": ov_summary,
        "rating_plot": rating_plot,
        "pct_negative_plot": pct_negative_plot,
        "critical_plot": critical_plot,
        "top_issues": ov_top_issues,
    }


def build_trends_page() -> dict[str, Any]:
    with gr.Column(visible=False, elem_classes=["ri-page"], elem_id="page_trends") as page:
        build_section_header("Trends & Anomalies", "Anomaly monitor placeholder for MVP")
        with gr.Group(elem_classes=["ri-card"]):
            gr.Markdown(
                "Anomaly detection output is currently a placeholder. "
                "Spike explanations and drill-throughs can plug in here without layout changes."
            )
            anomaly_placeholder = pd.DataFrame(
                [
                    {
                        "day": "-",
                        "metric": "-",
                        "z_score": "-",
                        "status": "No anomaly list wired yet",
                    }
                ]
            )
            anomaly_table = gr.Dataframe(value=anomaly_placeholder, interactive=False, label="Anomaly List")

    return {"page": page, "anomaly_table": anomaly_table}


def build_issues_page(default_start: str, default_end: str, categories: list[str], issue_labels: list[str], versions: list[str]) -> dict[str, Any]:
    with gr.Column(visible=False, elem_classes=["ri-page"], elem_id="page_issues") as page:
        build_section_header("Issues Drilldown", "Slice review-level detail and supporting evidence")
        date_controls = build_date_controls("issues", default_start, default_end)

        with gr.Group(elem_classes=["ri-card"]):
            with gr.Row():
                dr_category = gr.Dropdown(choices=categories, value="", label="Category")
                dr_issue = gr.Dropdown(choices=issue_labels, value="", label="Issue Label")
                dr_version = gr.Dropdown(choices=[""] + versions, value="", label="Version")
            with gr.Row():
                dr_page_size = gr.Dropdown(choices=[10, 25, 50, 100], value=25, label="Page Size")
                dr_page = gr.Number(value=1, precision=0, label="Page")
                dr_run = gr.Button("Run Drilldown", variant="primary")

        dr_status = gr.Markdown(elem_classes=["ri-muted-text"])

        with gr.Group(elem_classes=["ri-card"]):
            dr_table = gr.Dataframe(label="Reviews", interactive=False)

        with gr.Group(elem_classes=["ri-card"]):
            dr_quotes = gr.Markdown(label="Evidence Quotes")

    return {
        "container": page,
        "date": date_controls,
        "category": dr_category,
        "issue": dr_issue,
        "version": dr_version,
        "page_size": dr_page_size,
        "page_number": dr_page,
        "run": dr_run,
        "status": dr_status,
        "table": dr_table,
        "quotes": dr_quotes,
    }


def build_release_diff_page(versions: list[str], version_a_default: str | None, version_b_default: str | None) -> dict[str, Any]:
    with gr.Column(visible=False, elem_classes=["ri-page"], elem_id="page_release") as page:
        build_section_header("Release Diff", "Compare KPI shifts between two app versions")
        with gr.Group(elem_classes=["ri-card"]):
            with gr.Row():
                rel_a = gr.Dropdown(choices=versions, value=version_a_default, label="Version A")
                rel_b = gr.Dropdown(choices=versions, value=version_b_default, label="Version B")
                rel_compare = gr.Button("Compare", variant="primary")
            rel_table = gr.Dataframe(label="KPI Delta (B - A)", interactive=False)
            gr.Markdown(
                "Narrative generation placeholder: release notes summary will be added in a later step.",
                elem_classes=["ri-muted-text"],
            )

    return {
        "page": page,
        "version_a": rel_a,
        "version_b": rel_b,
        "compare": rel_compare,
        "table": rel_table,
    }


def build_exec_brief_page(default_start: str, default_end: str, categories: list[str], issue_labels: list[str], versions: list[str]) -> dict[str, Any]:
    with gr.Column(visible=False, elem_classes=["ri-page"], elem_id="page_exec") as page:
        build_section_header("Executive Brief", "Generate structured leadership-ready weekly brief")
        date_controls = build_date_controls("exec", default_start, default_end)

        with gr.Group(elem_classes=["ri-card"]):
            with gr.Row():
                eb_category = gr.Dropdown(choices=categories, value="", label="Category")
                eb_version = gr.Dropdown(choices=[""] + versions, value="", label="Version")
                eb_issue = gr.Dropdown(choices=issue_labels, value="", label="Issue Label")
            eb_generate = gr.Button("Generate Executive Brief", variant="primary")

        with gr.Group(elem_classes=["ri-card"]):
            eb_board = gr.HTML(label="Executive Brief Narrative", elem_classes=["ri-board"])
            with gr.Accordion("Raw JSON", open=False, elem_classes=["ri-card"]):
                eb_raw = gr.JSON(label="Executive Brief JSON")

        with gr.Group(elem_classes=["ri-card"]):
            eb_kpi_table = gr.Dataframe(label="KPI Summary", interactive=False)
            eb_download = gr.File(label="Download Executive Brief JSON")

    return {
        "page": page,
        "date": date_controls,
        "category": eb_category,
        "version": eb_version,
        "issue": eb_issue,
        "generate": eb_generate,
        "board": eb_board,
        "raw": eb_raw,
        "kpi_table": eb_kpi_table,
        "download": eb_download,
    }


def build_sprint_planner_page(default_start: str, default_end: str, categories: list[str], issue_labels: list[str], versions: list[str]) -> dict[str, Any]:
    with gr.Column(visible=False, elem_classes=["ri-page"], elem_id="page_sprint") as page:
        build_section_header("Sprint Planner", "Ticket board view over generated sprint backlog")
        date_controls = build_date_controls("sprint", default_start, default_end)

        with gr.Group(elem_classes=["ri-card"]):
            with gr.Row():
                sp_category = gr.Dropdown(choices=categories, value="", label="Category")
                sp_version = gr.Dropdown(choices=[""] + versions, value="", label="Version")
                sp_issue = gr.Dropdown(choices=issue_labels, value="", label="Issue Label")
            sp_generate = gr.Button("Generate Backlog", variant="primary")

        with gr.Row(equal_height=False):
            with gr.Column(scale=7):
                sp_board = gr.HTML(label="Sprint Ticket Board", elem_classes=["ri-board"])
            with gr.Column(scale=5):
                with gr.Accordion("Raw JSON", open=False, elem_classes=["ri-card"]):
                    sp_raw = gr.JSON(label="Backlog JSON")

        with gr.Group(elem_classes=["ri-card"]):
            sp_summary = gr.Dataframe(label="Backlog Summary", interactive=False)

        with gr.Row():
            sp_csv_download = gr.File(label="Download Ticket CSV")
            sp_json_download = gr.File(label="Download Sprint Backlog JSON")

    return {
        "page": page,
        "date": date_controls,
        "category": sp_category,
        "version": sp_version,
        "issue": sp_issue,
        "generate": sp_generate,
        "board": sp_board,
        "raw": sp_raw,
        "summary": sp_summary,
        "csv_download": sp_csv_download,
        "json_download": sp_json_download,
    }
