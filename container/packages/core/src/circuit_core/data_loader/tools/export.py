"""export_segment tool — export segment(s) to files for Layer 1 consumption."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from circuit_core.data_loader.storage import get_backend

logger = logging.getLogger("data-loader")


def run_export_segment(
    dataset_id: str,
    segment_id: str | None = None,
    fmt: str = "csv",
    output_dir: str = ".",
) -> dict:
    """Export a specific segment or all segments for a dataset to files.

    Segments are DuckDB tables named 'seg_{dataset_id}_*'.
    """
    backend = get_backend()

    if fmt not in ("csv", "parquet"):
        return {"error": f"Unsupported format '{fmt}'. Use 'csv' or 'parquet'."}

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    exported = []

    if segment_id:
        # Export a single segment
        table_name = _resolve_table(backend, dataset_id, segment_id)
        if table_name is None:
            return {"error": f"Segment '{segment_id}' not found for dataset '{dataset_id}'."}

        result = _export_one(backend, table_name, segment_id, fmt, out_dir)
        if result:
            exported.append(result)
    else:
        # Export all segments for this dataset
        tables = _find_segment_tables(backend, dataset_id)
        if not tables:
            return {"error": f"No segments found for dataset '{dataset_id}'. Create segments first with create_segments."}

        for table_name, seg_id in tables:
            result = _export_one(backend, table_name, seg_id, fmt, out_dir)
            if result:
                exported.append(result)

    return {"exported": exported}


def _resolve_table(backend, dataset_id: str, segment_id: str) -> str | None:
    """Find the DuckDB table name for a segment_id."""
    # segment_id format: {dataset_id}_{safe_label}
    table_name = f"seg_{segment_id}"
    if backend.table_exists(table_name):
        return table_name

    # Try with dataset prefix
    table_name = f"seg_{dataset_id}_{segment_id}"
    if backend.table_exists(table_name):
        return table_name

    return None


def _find_segment_tables(backend, dataset_id: str) -> list[tuple[str, str]]:
    """Find all segment tables for a dataset. Returns [(table_name, segment_id)]."""
    prefix = f"seg_{dataset_id}_"
    try:
        tables_df = backend.query_sql(
            "SELECT table_name FROM information_schema.tables "
            f"WHERE table_name LIKE '{prefix}%'"
        )
        results = []
        for _, row in tables_df.iterrows():
            table_name = row["table_name"]
            seg_id = table_name[4:]  # strip 'seg_' prefix
            results.append((table_name, seg_id))
        return results
    except Exception as e:
        logger.warning("Failed to list segment tables: %s", e)
        return []


def _export_one(backend, table_name: str, segment_id: str, fmt: str, out_dir: Path) -> dict | None:
    """Export a single segment table."""
    ext = "parquet" if fmt == "parquet" else "csv"
    output_path = str(out_dir / f"{segment_id}.{ext}")

    try:
        row_count = backend.export_table(table_name, output_path, fmt=fmt)
        size_mb = round(os.path.getsize(output_path) / (1024 * 1024), 3)

        # Extract label from segment_id (reverse the safe_name operation somewhat)
        label = segment_id.split("_", 1)[1] if "_" in segment_id else segment_id

        return {
            "segment_id": segment_id,
            "label": label,
            "path": output_path,
            "rows": row_count,
            "size_mb": size_mb,
        }
    except Exception as e:
        logger.warning("Failed to export '%s': %s", table_name, e)
        return None
