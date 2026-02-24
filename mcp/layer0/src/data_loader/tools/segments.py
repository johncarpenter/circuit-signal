"""list_segments tool — explore unique values in a column."""

from __future__ import annotations

import logging

from data_loader.storage import get_backend

logger = logging.getLogger("data-loader")


def run_list_segments(dataset_name: str, column: str) -> dict:
    """List unique values and counts for a column in a loaded dataset."""
    backend = get_backend()

    # Verify dataset exists
    try:
        schema = backend.schema(dataset_name)
    except Exception as e:
        return {"error": f"Dataset '{dataset_name}' not found. Load it first with load_dataset. ({e})"}

    # Verify column exists
    col_names = [c["name"] for c in schema["columns"]]
    if column not in col_names:
        return {
            "error": f"Column '{column}' not found in '{dataset_name}'.",
            "available_columns": col_names,
        }

    values = backend.unique_values(dataset_name, column)

    return {
        "dataset_name": dataset_name,
        "column": column,
        "unique_count": len(values),
        "total_rows": schema["row_count"],
        "values": values,
    }
