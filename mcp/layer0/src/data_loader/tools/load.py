"""load_dataset tool — load raw data, profile columns, detect hierarchies."""

from __future__ import annotations

import logging
import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from data_loader.storage import get_backend

logger = logging.getLogger("data-loader")

# Heuristic thresholds
_MAX_UNIQUE_RATIO = 0.5
_MIN_UNIQUE = 2
_MAX_UNIQUE = 300  # generous — suggest_segments enforces max_segments
_ID_CARDINALITY_RATIO = 0.5  # if unique/total > this, likely an identifier


def run_load(data_path: str, dataset_name: str | None = None) -> dict:
    """Load a file into the store and return rich profile + suggestions."""
    p = Path(data_path).resolve()
    if not p.exists():
        return {"error": f"File not found: {data_path}"}

    name = dataset_name or p.stem
    data_dir = str(p.parent)

    backend = get_backend(data_dir)
    schema = backend.load(str(p), name)

    # Read a sample for heuristic analysis
    df_sample = _read_sample(str(p), n=5000)
    total_rows = schema["row_count"]

    # Profile each column
    columns_profile = []
    timestamp_candidates = []
    numeric_columns = []
    segment_candidates = []

    for col_info in schema["columns"]:
        col_name = col_info["name"]
        col_type = col_info["type"]
        profile = _profile_column(df_sample, col_name, col_type, total_rows)
        columns_profile.append(profile)

        if profile["role"] == "timestamp":
            timestamp_candidates.append(col_name)
        elif profile["role"] == "numeric":
            numeric_columns.append(col_name)

        if profile["is_segment_candidate"]:
            segment_candidates.append({
                "column": col_name,
                "cardinality": profile["cardinality"],
                "min_group_size": profile["stats"].get("min_group_size", 0),
                "max_group_size": profile["stats"].get("max_group_size", 0),
                "top_values": profile["stats"].get("top_values", []),
            })

    # Detect hierarchies among segment candidates
    seg_col_names = [s["column"] for s in segment_candidates]
    detected_hierarchies = _detect_hierarchies(df_sample, seg_col_names)

    # File info
    file_size_mb = round(os.path.getsize(str(p)) / (1024 * 1024), 2)

    return {
        "dataset_id": name,
        "file_info": {
            "format": p.suffix.lstrip(".").lower(),
            "rows": total_rows,
            "columns": len(schema["columns"]),
            "size_mb": file_size_mb,
        },
        "columns": columns_profile,
        "timestamp_candidates": timestamp_candidates,
        "numeric_columns": numeric_columns,
        "segment_candidates": segment_candidates,
        "detected_hierarchies": detected_hierarchies,
        "sample_rows": df_sample.head(3).to_dict(orient="records"),
    }


def _read_sample(data_path: str, n: int = 5000) -> pd.DataFrame:
    """Read up to n rows for heuristic analysis."""
    p = Path(data_path)
    ext = p.suffix.lower()
    if ext == ".csv":
        return pd.read_csv(data_path, nrows=n)
    elif ext in (".parquet", ".pq"):
        df = pd.read_parquet(data_path)
        return df.head(n)
    elif ext == ".json":
        df = pd.read_json(data_path)
        return df.head(n)
    return pd.DataFrame()


def _profile_column(df: pd.DataFrame, col_name: str, col_type: str, total_rows: int) -> dict:
    """Profile a single column and classify its role."""
    if col_name not in df.columns:
        return {
            "name": col_name, "role": "unknown", "dtype": col_type,
            "cardinality": 0, "null_pct": 0.0, "stats": {},
            "is_segment_candidate": False, "segment_candidate_reason": None,
        }

    series = df[col_name]
    cardinality = int(series.nunique())
    null_pct = round(float(series.isna().mean()) * 100, 2)
    unique_ratio = cardinality / max(total_rows, 1)

    # Classify role
    role = _classify_role(series, col_name, col_type, cardinality, unique_ratio, total_rows)

    # Build role-specific stats
    stats = _build_stats(series, role, cardinality)

    # Determine segment candidacy
    is_candidate = False
    candidate_reason = None
    if role == "categorical":
        if _MIN_UNIQUE <= cardinality <= _MAX_UNIQUE and unique_ratio < _MAX_UNIQUE_RATIO:
            is_candidate = True
            candidate_reason = f"Categorical with {cardinality} unique values"
            # Add group size info
            counts = series.value_counts()
            stats["min_group_size"] = int(counts.min())
            stats["max_group_size"] = int(counts.max())
            stats["top_values"] = [
                {"value": str(v), "count": int(c)}
                for v, c in counts.head(10).items()
            ]

    return {
        "name": col_name,
        "role": role,
        "dtype": col_type,
        "cardinality": cardinality,
        "null_pct": null_pct,
        "stats": stats,
        "is_segment_candidate": is_candidate,
        "segment_candidate_reason": candidate_reason,
    }


def _classify_role(
    series: pd.Series,
    col_name: str,
    col_type: str,
    cardinality: int,
    unique_ratio: float,
    total_rows: int,
) -> str:
    """Classify a column into: timestamp, numeric, categorical, identifier, text, boolean."""
    name_lower = col_name.lower()

    # Boolean
    if series.dtype == bool or (cardinality == 2 and set(series.dropna().unique()) <= {0, 1, True, False, "true", "false", "True", "False"}):
        return "boolean"

    # Timestamp detection
    if str(series.dtype).startswith("datetime"):
        return "timestamp"
    time_keywords = ["date", "time", "timestamp", "created", "updated", "at"]
    if any(kw in name_lower for kw in time_keywords):
        sample = series.dropna().head(100)
        if len(sample) > 0:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    parsed = pd.to_datetime(sample, utc=True)
                if parsed.notna().sum() > len(sample) * 0.8:
                    return "timestamp"
            except (ValueError, TypeError):
                pass

    # Identifier detection: high cardinality + name hints
    id_keywords = ["id", "uuid", "key", "code", "sku", "barcode"]
    if unique_ratio > _ID_CARDINALITY_RATIO and any(kw in name_lower for kw in id_keywords):
        return "identifier"
    if unique_ratio > 0.9 and cardinality > 100:
        return "identifier"

    # Numeric
    if pd.api.types.is_numeric_dtype(series):
        # Could be encoded category (small int with low cardinality)
        if pd.api.types.is_integer_dtype(series) and cardinality <= 50:
            return "categorical"
        return "numeric"

    # Text vs categorical
    if series.dtype in (object, "string"):
        if cardinality > _MAX_UNIQUE or unique_ratio > _MAX_UNIQUE_RATIO:
            return "text"
        return "categorical"

    return "categorical"


def _build_stats(series: pd.Series, role: str, cardinality: int) -> dict:
    """Build role-specific statistics."""
    stats: dict = {}
    if role == "numeric":
        desc = series.describe()
        stats = {
            "min": _safe(desc.get("min")),
            "max": _safe(desc.get("max")),
            "mean": _safe(desc.get("mean")),
            "std": _safe(desc.get("std")),
            "median": _safe(series.median()),
        }
    elif role == "timestamp":
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                parsed = pd.to_datetime(series.dropna(), utc=True)
            stats = {
                "min": str(parsed.min()),
                "max": str(parsed.max()),
                "range_days": (parsed.max() - parsed.min()).days,
            }
        except Exception:
            stats = {}
    elif role == "categorical":
        counts = series.value_counts()
        stats = {
            "top_values": [
                {"value": str(v), "count": int(c)}
                for v, c in counts.head(5).items()
            ],
        }
    return stats


def _detect_hierarchies(df: pd.DataFrame, candidate_cols: list[str]) -> list[dict]:
    """Detect hierarchical relationships among candidate segmentation columns.

    Column A is a parent of column B if every unique value of B maps to exactly
    one value of A (but A maps to multiple values of B).
    """
    if len(candidate_cols) < 2:
        return []

    hierarchies = []
    for parent_col in candidate_cols:
        for child_col in candidate_cols:
            if parent_col == child_col:
                continue
            # Check: does every value of child_col map to exactly one parent_col?
            mapping = df[[child_col, parent_col]].drop_duplicates()
            child_to_parents = mapping.groupby(child_col)[parent_col].nunique()
            if (child_to_parents == 1).all():
                parent_card = df[parent_col].nunique()
                child_card = df[child_col].nunique()
                # Only report if parent is coarser (fewer values)
                if parent_card < child_card:
                    hierarchies.append({
                        "columns": [parent_col, child_col],
                        "description": (
                            f"{parent_col} ({parent_card} values) → "
                            f"{child_col} ({child_card} values): "
                            f"each {child_col} belongs to exactly one {parent_col}"
                        ),
                    })

    # Deduplicate: if A→B and B→C, report as A→B→C
    hierarchies = _merge_hierarchy_chains(hierarchies)
    return hierarchies


def _merge_hierarchy_chains(hierarchies: list[dict]) -> list[dict]:
    """Merge pairwise hierarchies into chains (A→B, B→C → A→B→C)."""
    if len(hierarchies) <= 1:
        return hierarchies

    # Build adjacency: parent → child
    edges: dict[str, str] = {}
    for h in hierarchies:
        parent, child = h["columns"]
        edges[parent] = child

    # Find chain starts (parents that are not children of anything)
    all_children = set(edges.values())
    starts = [p for p in edges if p not in all_children]

    chains = []
    for start in starts:
        chain = [start]
        current = start
        while current in edges:
            chain.append(edges[current])
            current = edges[current]
        if len(chain) >= 2:
            chains.append({
                "columns": chain,
                "description": " → ".join(chain),
            })

    # If no chains found (cycles or other oddities), return originals
    return chains if chains else hierarchies


def _safe(val):
    """Convert numpy/pandas types to JSON-serializable Python types."""
    if val is None:
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return round(float(val), 4)
    if isinstance(val, pd.Timestamp):
        return str(val)
    if isinstance(val, np.bool_):
        return bool(val)
    return val
