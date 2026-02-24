"""
Baseline report generator — produces a Markdown report with embedded charts
from Mode 1 decomposition results.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger("signal-discovery.report")

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    logger.info("matplotlib not installed — baseline reports will be text-only")


def generate_baseline_report(
    baselines: list[dict],
    dataset_summary: dict,
    data_path: str,
    detected_freq: str,
    df: pd.DataFrame,
) -> str:
    """
    Generate a Markdown baseline report with trend, seasonality, and residual charts.

    Returns the path to the generated report file.
    """
    stem = Path(data_path).stem
    report_name = f"{stem}_{detected_freq}_baseline_report.md"
    charts_dir_name = f"{stem}_{detected_freq}_baseline_charts"

    report_path = Path.cwd() / report_name
    charts_dir = Path.cwd() / charts_dir_name

    if HAS_MATPLOTLIB:
        charts_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []

    # Header
    lines.append(f"# Baseline Report: {stem}")
    lines.append("")

    # Dataset summary table
    lines.append("## Dataset Summary")
    lines.append("")
    lines.append("| Property | Value |")
    lines.append("|----------|-------|")
    lines.append(f"| Rows | {dataset_summary.get('rows', 'N/A'):,} |")

    time_range = dataset_summary.get("time_range", {})
    lines.append(f"| Start | {time_range.get('start', 'N/A')} |")
    lines.append(f"| End | {time_range.get('end', 'N/A')} |")
    lines.append(f"| Frequency | {dataset_summary.get('frequency_detected', 'N/A')} |")
    lines.append(f"| Columns Analyzed | {dataset_summary.get('columns_analyzed', 'N/A')} |")

    quality = dataset_summary.get("data_quality", {})
    if quality:
        completeness = quality.get("completeness_pct")
        if completeness is not None:
            lines.append(f"| Data Completeness | {completeness}% |")
    lines.append("")

    # Per-column sections
    for bl in baselines:
        col = bl.get("column", "unknown")
        lines.append(f"## Column: {col}")
        lines.append("")

        if bl.get("error"):
            lines.append(f"> Decomposition failed: {bl['error']}")
            lines.append("")
            continue

        variance_explained = bl.get("variance_explained")
        if variance_explained is not None:
            lines.append(f"**Variance explained by trend + seasonality:** {round(variance_explained * 100, 1)}%")
            lines.append("")

        # Narrative
        narrative = bl.get("narrative", "")
        if narrative:
            lines.append(f"> {narrative}")
            lines.append("")

        # --- Trend ---
        trend_info = bl.get("trend", {})
        lines.append("### Trend Analysis")
        lines.append("")
        lines.append(f"- **Direction:** {trend_info.get('direction', 'N/A')}")
        lines.append(f"- **Rate per period:** {trend_info.get('rate_per_period', 'N/A')}")

        change_points = trend_info.get("change_points", [])
        if change_points:
            lines.append(f"- **Change points:** {len(change_points)}")
            for cp in change_points:
                lines.append(f"  - {cp.get('timestamp', 'N/A')}: {cp.get('direction', '')} (magnitude: {cp.get('magnitude', 'N/A')})")
        lines.append("")

        # Trend chart
        if HAS_MATPLOTLIB and "_trend_values" in bl and "_index" in bl:
            chart_path = _render_trend_chart(bl, col, df, change_points, charts_dir)
            if chart_path:
                lines.append(f"![Trend: {col}]({charts_dir_name}/{chart_path.name})")
                lines.append("")

        # --- Seasonality ---
        seasonality = bl.get("seasonality", [])
        if seasonality:
            lines.append("### Seasonality")
            lines.append("")
            for s in seasonality:
                label = s.get("period_label", "unknown")
                lines.append(f"**{label.capitalize()} pattern** (period={s.get('period', 'N/A')})")
                lines.append(f"- Peak phase: {s.get('peak_phase', 'N/A')}")
                lines.append(f"- Strength: {s.get('strength', 'N/A')}")
                lines.append("")

            # Seasonality chart
            if HAS_MATPLOTLIB and "_trend_values" in bl and "_residual_values" in bl and "_index" in bl:
                chart_path = _render_seasonality_chart(bl, col, detected_freq, df, charts_dir)
                if chart_path:
                    lines.append(f"![Seasonality: {col}]({charts_dir_name}/{chart_path.name})")
                    lines.append("")
        else:
            lines.append("### Seasonality")
            lines.append("")
            lines.append("No significant seasonal patterns detected.")
            lines.append("")

        # --- Residual ---
        resid_profile = bl.get("residual_profile", {})
        lines.append("### Residual Analysis")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Std Dev | {resid_profile.get('std', 'N/A')} |")
        lines.append(f"| Stationary | {resid_profile.get('is_stationary', 'N/A')} |")
        lines.append(f"| Distribution | {resid_profile.get('distribution', 'N/A')} |")
        if "skewness" in resid_profile:
            lines.append(f"| Skewness | {resid_profile['skewness']} |")
        if "kurtosis" in resid_profile:
            lines.append(f"| Kurtosis | {resid_profile['kurtosis']} |")
        lines.append("")

        # Residual chart
        if HAS_MATPLOTLIB and "_residual_values" in bl and "_index" in bl:
            chart_path = _render_residual_chart(bl, col, resid_profile, charts_dir)
            if chart_path:
                lines.append(f"![Residuals: {col}]({charts_dir_name}/{chart_path.name})")
                lines.append("")

        lines.append("---")
        lines.append("")

    report_content = "\n".join(lines)
    report_path.write_text(report_content)
    logger.info(f"Baseline report written to {report_path}")

    return str(report_path)


# ---------------------------------------------------------------------------
# Chart renderers
# ---------------------------------------------------------------------------


def _render_trend_chart(
    bl: dict,
    col: str,
    df: pd.DataFrame,
    change_points: list[dict],
    charts_dir: Path,
) -> Path | None:
    """Render original data with trend overlay and change point markers."""
    try:
        idx = pd.to_datetime(bl["_index"])
        trend = np.array(bl["_trend_values"])

        # Get original values aligned to the decomposition index
        if col in df.columns:
            original = df[col].reindex(idx)
        else:
            original = None

        fig, ax = plt.subplots(figsize=(12, 4))

        if original is not None:
            ax.plot(idx, original.values, color="#B0BEC5", linewidth=0.6, alpha=0.7, label="Original")
        ax.plot(idx, trend, color="#1565C0", linewidth=2, label="Trend")

        # Change point vertical lines
        for cp in change_points:
            ts = pd.Timestamp(cp["timestamp"])
            ax.axvline(x=ts, color="#E53935", linestyle="--", linewidth=1, alpha=0.7)

        ax.set_title(f"Trend: {col}", fontsize=13, fontweight="bold")
        ax.set_xlabel("")
        ax.legend(loc="upper left", fontsize=9)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate()
        fig.tight_layout()

        out = charts_dir / f"{col}_trend.png"
        fig.savefig(out, dpi=120)
        plt.close(fig)
        return out
    except Exception as e:
        logger.warning(f"Failed to render trend chart for '{col}': {e}")
        return None


def _render_seasonality_chart(
    bl: dict,
    col: str,
    freq: str,
    df: pd.DataFrame,
    charts_dir: Path,
) -> Path | None:
    """Render seasonal pattern as a bar chart grouped by cycle position."""
    try:
        idx = pd.to_datetime(bl["_index"])
        trend = np.array(bl["_trend_values"])
        residual = np.array(bl["_residual_values"])

        if col not in df.columns:
            return None
        original = df[col].reindex(idx).values

        # seasonal = original - trend - residual (additive decomposition)
        seasonal = original - trend - residual

        seasonal_series = pd.Series(seasonal, index=idx)

        seasonality_info = bl.get("seasonality", [])
        if not seasonality_info:
            return None

        n_patterns = len(seasonality_info)
        fig, axes = plt.subplots(1, n_patterns, figsize=(6 * n_patterns, 4), squeeze=False)

        for i, s_info in enumerate(seasonality_info):
            ax = axes[0, i]
            label = s_info.get("period_label", "unknown")

            if label == "daily" and freq in ("hourly", "sub_hourly"):
                grouped = seasonal_series.groupby(seasonal_series.index.hour).mean()
                x_labels = [f"{h:02d}:00" for h in grouped.index]
                ax.bar(range(len(grouped)), grouped.values, color="#42A5F5", edgecolor="#1565C0")
                ax.set_xticks(range(len(grouped)))
                ax.set_xticklabels(x_labels, rotation=45, fontsize=7)
                ax.set_xlabel("Hour of Day")
            elif label == "weekly" and freq in ("daily", "hourly"):
                grouped = seasonal_series.groupby(seasonal_series.index.dayofweek).mean()
                day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                ax.bar(range(len(grouped)), grouped.values, color="#66BB6A", edgecolor="#2E7D32")
                ax.set_xticks(range(len(grouped)))
                ax.set_xticklabels(day_names)
                ax.set_xlabel("Day of Week")
            elif label == "annual" and freq in ("daily", "weekly", "monthly"):
                grouped = seasonal_series.groupby(seasonal_series.index.month).mean()
                month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                ax.bar(range(len(grouped)), grouped.values, color="#FFA726", edgecolor="#E65100")
                ax.set_xticks(range(len(grouped)))
                ax.set_xticklabels(month_names, rotation=45, fontsize=8)
                ax.set_xlabel("Month")
            else:
                # Generic: group by position in cycle
                period = s_info.get("period", 1)
                positions = np.arange(len(seasonal_series)) % period
                grouped = seasonal_series.groupby(positions).mean()
                ax.bar(range(len(grouped)), grouped.values, color="#AB47BC", edgecolor="#6A1B9A")
                ax.set_xlabel(f"Position in {label} cycle")

            ax.set_ylabel("Seasonal Effect")
            ax.set_title(f"{label.capitalize()} Seasonality: {col}", fontsize=11, fontweight="bold")
            ax.axhline(y=0, color="gray", linestyle="-", linewidth=0.5)

        fig.tight_layout()
        out = charts_dir / f"{col}_seasonality.png"
        fig.savefig(out, dpi=120)
        plt.close(fig)
        return out
    except Exception as e:
        logger.warning(f"Failed to render seasonality chart for '{col}': {e}")
        return None


def _render_residual_chart(
    bl: dict,
    col: str,
    resid_profile: dict,
    charts_dir: Path,
) -> Path | None:
    """Render residual histogram with statistical annotations."""
    try:
        residual = np.array(bl["_residual_values"])
        residual = residual[~np.isnan(residual)]

        if len(residual) < 10:
            return None

        fig, ax = plt.subplots(figsize=(8, 4))

        ax.hist(residual, bins=min(50, max(20, len(residual) // 50)),
                color="#78909C", edgecolor="#455A64", alpha=0.8)

        # Annotations
        std = resid_profile.get("std", np.std(residual))
        skew = resid_profile.get("skewness", 0)
        kurt = resid_profile.get("kurtosis", 0)
        dist = resid_profile.get("distribution", "unknown")

        annotation = (
            f"std = {std:.4f}\n"
            f"skewness = {skew:.4f}\n"
            f"kurtosis = {kurt:.4f}\n"
            f"distribution: {dist}"
        )
        ax.text(0.97, 0.95, annotation, transform=ax.transAxes,
                fontsize=9, verticalalignment="top", horizontalalignment="right",
                bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.8))

        # Mark std bands
        mean = np.mean(residual)
        for mult, alpha in [(1, 0.3), (2, 0.15)]:
            ax.axvspan(mean - mult * std, mean + mult * std,
                       alpha=alpha, color="#42A5F5", label=f"{mult}\u03c3")

        ax.set_title(f"Residual Distribution: {col}", fontsize=13, fontweight="bold")
        ax.set_xlabel("Residual Value")
        ax.set_ylabel("Frequency")
        ax.legend(loc="upper left", fontsize=9)
        fig.tight_layout()

        out = charts_dir / f"{col}_residuals.png"
        fig.savefig(out, dpi=120)
        plt.close(fig)
        return out
    except Exception as e:
        logger.warning(f"Failed to render residual chart for '{col}': {e}")
        return None
