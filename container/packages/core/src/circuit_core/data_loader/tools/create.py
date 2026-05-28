"""create_segment tool — filter, aggregate, gap-fill, and export time series."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from circuit_core.data_loader.storage import get_backend

logger = logging.getLogger("data-loader")


def run_create_segment(
    dataset_name: str,
    timestamp_col: str,
    metrics: list[dict],
    freq: str = "hourly",
    segment_col: str | None = None,
    segment_value: str | None = None,
    output_path: str | None = None,
) -> dict:
    """Filter + aggregate + gap-fill + write CSV.

    Args:
        freq: Aggregation frequency (default: 'hourly'). One of 'hourly', 'daily', 'weekly', 'monthly'.
    """
    backend = get_backend()

    # Validate inputs
    try:
        schema = backend.schema(dataset_name)
    except Exception as e:
        return {"error": f"Dataset '{dataset_name}' not found. Load it first. ({e})"}

    valid_freqs = ["hourly", "daily", "weekly", "monthly"]
    if freq not in valid_freqs:
        return {"error": f"Invalid freq '{freq}'. Use one of: {valid_freqs}"}

    # Run aggregation
    try:
        df = backend.aggregate(
            dataset_name=dataset_name,
            timestamp_col=timestamp_col,
            freq=freq,
            metrics=metrics,
            segment_col=segment_col,
            segment_value=segment_value,
        )
    except Exception as e:
        return {"error": f"Aggregation failed: {e}"}

    if df.empty:
        return {"error": "No data after filtering. Check segment_col/segment_value."}

    # Determine output path
    if output_path:
        out = Path(output_path)
    else:
        suffix = f"_{segment_value[:8]}" if segment_value else ""
        filename = f"{dataset_name}{suffix}_{freq}.csv"
        out = Path.cwd() / "data" / filename

    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    logger.info("Wrote %d rows to %s", len(df), out)

    # Build summary stats
    metric_cols = [c for c in df.columns if c != "period"]
    stats = {}
    for col in metric_cols:
        vals = df[col]
        stats[col] = {
            "min": _safe(vals.min()),
            "max": _safe(vals.max()),
            "mean": _safe(vals.mean()),
            "sum": _safe(vals.sum()),
            "zeros": int((vals == 0).sum()),
        }

    # Preview rows
    preview = df.head(5).to_dict(orient="records")
    for row in preview:
        for k, v in row.items():
            row[k] = _safe(v)

    # Build suggested layer1 call
    value_cols = metric_cols
    suggested_layer1 = {
        "tool": "discover_baseline",
        "args": {
            "data_path": str(out),
            "timestamp_col": "period",
            "value_cols": value_cols,
            "freq": freq,
        },
    }

    return {
        "output_path": str(out),
        "rows": len(df),
        "period_range": {
            "start": str(df["period"].iloc[0]),
            "end": str(df["period"].iloc[-1]),
        },
        "metrics_summary": stats,
        "preview": preview,
        "gap_fill": True,
        "suggested_layer1_call": suggested_layer1,
    }


def _safe(val):
    """Convert numpy/pandas types to JSON-serializable Python types."""
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return round(float(val), 4)
    if isinstance(val, pd.Timestamp):
        return str(val)
    if isinstance(val, np.bool_):
        return bool(val)
    return val
