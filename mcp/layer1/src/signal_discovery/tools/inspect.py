"""
Tool: inspect_dataset

Quick exploratory scan of a dataset. Returns column info, data types,
timestamp candidates, basic stats, and sample rows.
"""

import os

import numpy as np
import pandas as pd

from signal_discovery.ingest import load_data, find_timestamp_candidates


def run_inspect(data_path: str, sample_rows: int = 5) -> dict:
    """Run dataset inspection and return structured results."""
    df, fmt = load_data(data_path)
    file_size_mb = os.path.getsize(data_path) / (1024 * 1024)

    ts_candidates = find_timestamp_candidates(df)

    columns_info = []
    for col in df.columns:
        col_data = df[col]
        info = {
            "name": col,
            "dtype": str(col_data.dtype),
            "nulls": int(col_data.isna().sum()),
            "unique": int(col_data.nunique()),
            "is_timestamp_candidate": col in ts_candidates,
            "is_numeric": pd.api.types.is_numeric_dtype(col_data),
            "sample_values": col_data.dropna().head(5).tolist(),
        }

        # Add stats for numeric columns
        if info["is_numeric"]:
            info["stats"] = {
                "min": _safe_scalar(col_data.min()),
                "max": _safe_scalar(col_data.max()),
                "mean": _safe_scalar(col_data.mean()),
                "std": _safe_scalar(col_data.std()),
            }
        else:
            info["stats"] = {
                "min": _safe_scalar(col_data.min()),
                "max": _safe_scalar(col_data.max()),
                "mean": None,
                "std": None,
            }

        columns_info.append(info)

    # Sample rows
    sample = df.head(sample_rows).to_dict(orient="records")

    return {
        "file_info": {
            "format": fmt,
            "rows": len(df),
            "columns": len(df.columns),
            "size_mb": round(file_size_mb, 2),
        },
        "columns": columns_info,
        "timestamp_candidates": ts_candidates,
        "sample_rows": sample,
    }


def _safe_scalar(val):
    """Convert numpy types to Python natives for JSON serialization."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, (np.bool_,)):
        return bool(val)
    if isinstance(val, pd.Timestamp):
        return val.isoformat()
    return val
