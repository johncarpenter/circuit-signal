"""create_segments tool — batch split data into segments by column(s)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

from circuit_core.data_loader.storage import get_backend

logger = logging.getLogger("data-loader")


def run_create_segments(
    dataset_id: str,
    segment_by: str | list[str],
    timestamp_col: str,
    value_cols: list[str] | None = None,
    min_segment_size: int = 50,
    export_format: str | None = None,
    export_dir: str | None = None,
) -> dict:
    """Split data into segments based on column(s), create DuckDB tables, optionally export."""
    backend = get_backend()

    try:
        schema = backend.schema(dataset_id)
    except Exception as e:
        return {"error": f"Dataset '{dataset_id}' not found. Load it first. ({e})"}

    col_names = [c["name"] for c in schema["columns"]]

    # Normalize segment_by to list
    if isinstance(segment_by, str):
        segment_by = [segment_by]

    for col in segment_by:
        if col not in col_names:
            return {"error": f"Column '{col}' not found. Available: {col_names}"}

    if timestamp_col not in col_names:
        return {"error": f"Timestamp column '{timestamp_col}' not found."}

    # Determine which columns to include in segments
    if value_cols:
        select_cols = list(set([timestamp_col] + segment_by + value_cols))
    else:
        # Include timestamp + all numeric columns
        df_sample = backend.get_dataframe(dataset_id, limit=100)
        numeric = [c for c in df_sample.columns if pd.api.types.is_numeric_dtype(df_sample[c])]
        select_cols = list(set([timestamp_col] + segment_by + numeric))

    # Validate all select columns exist
    select_cols = [c for c in select_cols if c in col_names]

    # Get distinct segment values
    df = backend.get_dataframe(dataset_id, columns=segment_by)
    segment_values = df.drop_duplicates().to_dict(orient="records")

    segments_created = []
    segments_dropped = 0

    # Prepare export directory
    if export_format and export_dir:
        out_dir = Path(export_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
    elif export_format:
        out_dir = Path.cwd() / "data" / "segments"
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = None

    for seg_vals in segment_values:
        # Build segment label
        label_parts = [str(seg_vals[col]) for col in segment_by]
        label = " > ".join(label_parts) if len(label_parts) > 1 else label_parts[0]

        # Build safe table/file name
        safe_label = _safe_name(label)
        table_name = f"seg_{dataset_id}_{safe_label}"
        segment_id = f"{dataset_id}_{safe_label}"

        # Build filter SQL
        cols_expr = ", ".join(f'"{c}"' for c in select_cols if c not in segment_by)
        # Always include segment columns for reference
        all_cols_expr = ", ".join(f'"{c}"' for c in select_cols)

        where_parts = []
        for col in segment_by:
            val = seg_vals[col]
            if isinstance(val, str):
                where_parts.append(f'"{col}" = \'{val}\'')
            elif val is None or (isinstance(val, float) and np.isnan(val)):
                where_parts.append(f'"{col}" IS NULL')
            else:
                where_parts.append(f'"{col}" = {val}')

        where_clause = " AND ".join(where_parts)
        sql = f'SELECT {all_cols_expr} FROM "{dataset_id}" WHERE {where_clause} ORDER BY "{timestamp_col}"'

        try:
            row_count = backend.create_table_from_query(table_name, sql)
        except Exception as e:
            logger.warning("Failed to create segment '%s': %s", label, e)
            continue

        # Check minimum size
        if row_count < min_segment_size:
            segments_dropped += 1
            logger.info("Dropped segment '%s' (%d rows < min %d)", label, row_count, min_segment_size)
            continue

        # Get time range
        try:
            ts_df = backend.query_sql(
                f'SELECT MIN("{timestamp_col}") as ts_min, MAX("{timestamp_col}") as ts_max FROM "{table_name}"'
            )
            time_range = {
                "start": str(ts_df["ts_min"].iloc[0]),
                "end": str(ts_df["ts_max"].iloc[0]),
            }
        except Exception:
            time_range = {"start": None, "end": None}

        # Export if requested
        export_path = None
        if export_format and out_dir:
            ext = "parquet" if export_format == "parquet" else "csv"
            export_path = str(out_dir / f"{segment_id}.{ext}")
            try:
                backend.export_table(table_name, export_path, fmt=export_format)
            except Exception as e:
                logger.warning("Failed to export segment '%s': %s", label, e)
                export_path = None

        segments_created.append({
            "segment_id": segment_id,
            "label": label,
            "filter_values": {col: str(seg_vals[col]) for col in segment_by},
            "row_count": row_count,
            "time_range": time_range,
            "export_path": export_path,
            "duckdb_table": table_name,
        })

    return {
        "dataset_id": dataset_id,
        "segment_by": segment_by,
        "segments_created": len(segments_created),
        "segments_dropped": segments_dropped,
        "segments": segments_created,
        "layer1_ready": export_format is not None and all(s["export_path"] for s in segments_created),
    }


def _safe_name(label: str) -> str:
    """Convert a segment label to a safe table/file name."""
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", label)
    safe = re.sub(r"_+", "_", safe).strip("_").lower()
    return safe[:60]
