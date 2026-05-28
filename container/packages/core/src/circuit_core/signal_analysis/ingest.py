"""
Shared data ingestion and utility functions.

Handles loading CSV/Parquet/JSON files, timestamp parsing, frequency detection,
and common data quality checks used across all tools.
"""

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd


def load_data(data_path: str) -> tuple[pd.DataFrame, str]:
    """
    Load a dataset from CSV, Parquet, or JSON.

    Returns:
        (DataFrame, format_string)
    """
    path = Path(data_path)
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(path)
        fmt = "csv"
    elif suffix in (".parquet", ".pq"):
        df = pd.read_parquet(path)
        fmt = "parquet"
    elif suffix == ".json":
        df = pd.read_json(path)
        fmt = "json"
    else:
        # Try CSV as fallback
        df = pd.read_csv(path)
        fmt = "csv"

    return df, fmt


def parse_timestamps(df: pd.DataFrame, timestamp_col: str) -> pd.DataFrame:
    """
    Parse and set the timestamp column as a DatetimeIndex.
    Sorts by time and removes duplicate timestamps (keeping last).
    """
    df = df.copy()
    df[timestamp_col] = pd.to_datetime(df[timestamp_col], utc=True)
    df = df.sort_values(timestamp_col).drop_duplicates(subset=[timestamp_col], keep="last")
    df = df.set_index(timestamp_col)
    return df


def detect_frequency(df: pd.DataFrame) -> str:
    """
    Infer the dominant frequency of a DatetimeIndex.

    Returns one of: 'sub_hourly', 'hourly', 'daily', 'weekly', 'monthly', 'quarterly', 'yearly'
    """
    if len(df) < 3:
        return "unknown"

    deltas = pd.Series(df.index).diff().dropna()
    median_delta = deltas.median()

    if median_delta <= pd.Timedelta(minutes=30):
        return "sub_hourly"
    elif median_delta <= pd.Timedelta(hours=2):
        return "hourly"
    elif median_delta <= pd.Timedelta(days=2):
        return "daily"
    elif median_delta <= pd.Timedelta(days=10):
        return "weekly"
    elif median_delta <= pd.Timedelta(days=45):
        return "monthly"
    elif median_delta <= pd.Timedelta(days=120):
        return "quarterly"
    else:
        return "yearly"


def get_seasonal_periods(freq: str) -> list[dict]:
    """
    Return appropriate seasonal periods for a given frequency.
    Each entry has 'period' (int) and 'label' (str).
    """
    mapping = {
        "sub_hourly": [
            {"period": 24, "label": "daily"},      # approximate
            {"period": 168, "label": "weekly"},
        ],
        "hourly": [
            {"period": 24, "label": "daily"},
            {"period": 168, "label": "weekly"},
        ],
        "daily": [
            {"period": 7, "label": "weekly"},
            {"period": 365, "label": "annual"},
        ],
        "weekly": [
            {"period": 52, "label": "annual"},
        ],
        "monthly": [
            {"period": 12, "label": "annual"},
        ],
        "quarterly": [
            {"period": 4, "label": "annual"},
        ],
    }
    return mapping.get(freq, [{"period": 7, "label": "weekly"}])


def find_numeric_columns(df: pd.DataFrame, threshold_nulls: float = 0.5) -> list[str]:
    """
    Identify numeric columns suitable for time-series analysis.
    Skips columns with >threshold_nulls fraction of nulls or zero variance.
    """
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    valid = []
    for col in numeric_cols:
        null_frac = df[col].isna().mean()
        if null_frac > threshold_nulls:
            continue
        if df[col].std() == 0 or pd.isna(df[col].std()):
            continue
        valid.append(col)
    return valid


def find_timestamp_candidates(df: pd.DataFrame) -> list[str]:
    """
    Heuristically identify columns that look like timestamps.
    Checks datetime dtypes and attempts parsing on object/string columns.
    """
    candidates = []
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            candidates.append(col)
            continue
        if df[col].dtype == object or str(df[col].dtype) == "string":
            # Try parsing a sample
            sample = df[col].dropna().head(20)
            if len(sample) == 0:
                continue
            try:
                parsed = pd.to_datetime(sample)
                # If >80% parsed successfully, consider it a timestamp
                if parsed.notna().mean() > 0.8:
                    candidates.append(col)
            except (ValueError, TypeError):
                continue
    return candidates


def data_quality_report(df: pd.DataFrame) -> dict:
    """
    Compute data quality metrics for a time-indexed DataFrame.
    """
    total_rows = len(df)
    if total_rows == 0:
        return {"completeness": 0, "gaps_detected": 0, "duplicate_timestamps": 0}

    # Check for gaps (periods where expected data is missing)
    if isinstance(df.index, pd.DatetimeIndex) and len(df) > 2:
        deltas = pd.Series(df.index).diff().dropna()
        median_delta = deltas.median()
        # A "gap" is any delta > 2x the median
        gaps = (deltas > median_delta * 2).sum()
    else:
        gaps = 0

    # Overall completeness (1 - fraction of null cells)
    completeness = 1.0 - df.isna().mean().mean()

    return {
        "completeness": round(float(completeness), 4),
        "gaps_detected": int(gaps),
        "duplicate_timestamps": 0,  # Already removed in parse_timestamps
    }


def file_hash(path: str) -> str:
    """Compute MD5 hash of a file for change detection."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_duration(duration_str: str) -> pd.Timedelta:
    """
    Parse a human-friendly duration string like '7d', '30d', '90d' into pd.Timedelta.
    """
    duration_str = duration_str.strip().lower()
    if duration_str.endswith("d"):
        return pd.Timedelta(days=int(duration_str[:-1]))
    elif duration_str.endswith("w"):
        return pd.Timedelta(weeks=int(duration_str[:-1]))
    elif duration_str.endswith("h"):
        return pd.Timedelta(hours=int(duration_str[:-1]))
    else:
        return pd.Timedelta(days=int(duration_str))
