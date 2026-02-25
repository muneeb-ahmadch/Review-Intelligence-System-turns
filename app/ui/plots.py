from __future__ import annotations

from datetime import date, datetime

import duckdb
import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter

from app.config import DUCKDB_PATH

matplotlib.use("Agg")

PALETTE = {
    "rating": "#2563eb",
    "negative": "#dc2626",
    "critical": "#ea580c",
    "grid": "#d1d9e6",
    "axis": "#334155",
    "fill_alpha": 0.12,
}


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


def get_daily_trends(
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
) -> pd.DataFrame:
    start = _to_date_string(start_date)
    end = _to_date_string(end_date)

    where = ["1=1"]
    params: list[str] = []
    if start:
        where.append("day >= ?")
        params.append(start)
    if end:
        where.append("day <= ?")
        params.append(end)

    query = f"""
        SELECT day, avg_rating, pct_negative, critical_count
        FROM daily_aggregates
        WHERE {' AND '.join(where)}
        ORDER BY day
    """

    with duckdb.connect(str(DUCKDB_PATH), read_only=True) as conn:
        rows = conn.execute(query, params).fetchall()

    df = pd.DataFrame(rows, columns=["day", "avg_rating", "pct_negative", "critical_count"])
    if not df.empty:
        df["day"] = pd.to_datetime(df["day"])
    return df


def _style_axes(ax, title: str, y_label: str) -> None:
    ax.set_title(title, fontsize=11, fontweight="bold", color=PALETTE["axis"], pad=10)
    ax.set_xlabel("Date", fontsize=9, color=PALETTE["axis"])
    ax.set_ylabel(y_label, fontsize=9, color=PALETTE["axis"])
    ax.tick_params(axis="both", labelsize=8, colors=PALETTE["axis"])
    ax.grid(axis="y", color=PALETTE["grid"], linewidth=0.8, alpha=0.7)
    ax.grid(axis="x", visible=False)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(PALETTE["grid"])
    ax.spines["bottom"].set_color(PALETTE["grid"])

    locator = mdates.AutoDateLocator(minticks=4, maxticks=8)
    formatter = mdates.ConciseDateFormatter(locator)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)


def _annotate_peak(ax, x_data: pd.Series, y_data: pd.Series, prefix: str = "Peak") -> None:
    if y_data.empty:
        return
    idx = int(y_data.idxmax())
    x_val = x_data.loc[idx]
    y_val = y_data.loc[idx]
    ax.scatter([x_val], [y_val], s=30, color="#0f172a", zorder=6)
    ax.annotate(
        f"{prefix}: {y_val:.1f}",
        xy=(x_val, y_val),
        xytext=(12, 8),
        textcoords="offset points",
        fontsize=8,
        color="#0f172a",
        bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": PALETTE["grid"], "alpha": 0.9},
    )


def _plot_series(
    df: pd.DataFrame,
    y_col: str,
    title: str,
    y_label: str,
    color: str,
    as_percent: bool = False,
    annotate_spike: bool = False,
):
    fig, ax = plt.subplots(figsize=(7.2, 3.2), dpi=120)

    if df.empty:
        ax.text(0.5, 0.5, "No data for selected date range", ha="center", va="center", color=PALETTE["axis"])
        ax.set_axis_off()
        fig.tight_layout()
        return fig

    y_values = df[y_col] * 100 if as_percent else df[y_col]
    ax.plot(
        df["day"],
        y_values,
        color=color,
        linewidth=2.2,
        marker="o",
        markersize=4,
        markerfacecolor="white",
        markeredgewidth=1.3,
        markeredgecolor=color,
        label=y_label,
    )
    ax.fill_between(df["day"], y_values, color=color, alpha=PALETTE["fill_alpha"])

    if as_percent:
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:.0f}%"))

    _style_axes(ax, title=title, y_label=y_label)

    if annotate_spike:
        _annotate_peak(ax, df["day"], y_values, prefix="Spike")

    ax.legend(loc="upper left", frameon=False, fontsize=8)
    fig.tight_layout()
    return fig


def plot_rating_trend(df: pd.DataFrame):
    return _plot_series(
        df=df,
        y_col="avg_rating",
        title="Average Rating Trend",
        y_label="Rating",
        color=PALETTE["rating"],
    )


def plot_pct_negative_trend(df: pd.DataFrame):
    return _plot_series(
        df=df,
        y_col="pct_negative",
        title="Negative Review Rate",
        y_label="Negative %",
        color=PALETTE["negative"],
        as_percent=True,
        annotate_spike=True,
    )


def plot_critical_count_trend(df: pd.DataFrame):
    return _plot_series(
        df=df,
        y_col="critical_count",
        title="Critical Review Count",
        y_label="Critical Reviews",
        color=PALETTE["critical"],
        annotate_spike=True,
    )
