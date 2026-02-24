"""
Data Loader MCP Server (Layer 0)

Exposes seven tools via MCP:
  1. load_dataset      — load raw data, profile columns, detect hierarchies
  2. suggest_segments  — auto-segmentation engine with quality scoring
  3. create_segments   — batch split data into segments by column(s)
  4. list_segments     — explore unique values in a column
  5. export_segment    — export segment(s) to files for Layer 1
  6. clean_dataset     — detect and fix data quality issues
  7. resolve_entities  — LLM-assisted entity name resolution
"""

import json
import logging

from mcp.server.fastmcp import FastMCP

from data_loader.tools.load import run_load
from data_loader.tools.segments import run_list_segments
from data_loader.tools.create import run_create_segment
from data_loader.tools.suggest import run_suggest_segments
from data_loader.tools.batch_create import run_create_segments
from data_loader.tools.export import run_export_segment
from data_loader.tools.clean import run_clean_dataset, run_llm_entity_resolution

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data-loader")

mcp = FastMCP(
    "Data Loader",
    instructions=(
        "Load raw transactional data, explore segments, and output properly "
        "aggregated time series for upstream analysis. "
        "Key capability: auto-segmentation — given a flat file, identify "
        "meaningful segmentation axes with quality scoring."
    ),
)


@mcp.tool()
def load_dataset(data_path: str, dataset_name: str | None = None) -> str:
    """
    Load a CSV, Parquet, or JSON file into the data store.
    Returns rich column profiling: roles (timestamp/numeric/categorical/identifier),
    per-column stats, segment candidates with reasons, and detected hierarchies.

    Args:
        data_path: Path to CSV, Parquet, or JSON file
        dataset_name: Optional name for the dataset (defaults to filename stem)
    """
    result = run_load(data_path=data_path, dataset_name=dataset_name)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def suggest_segments(
    dataset_id: str,
    timestamp_col: str,
    value_cols: list[str] | None = None,
    min_segment_size: int = 50,
    max_segments: int = 30,
) -> str:
    """
    Auto-segmentation engine. Analyzes a loaded dataset and recommends how to
    split it into independent time series for Layer 1 analysis.

    Scores each candidate segmentation by:
    - Differentiation (Kruskal-Wallis): do segments actually behave differently?
    - Balance: are segments roughly even in size?
    - Coverage: does each segment span the full time range?
    - Size: are segments large enough for meaningful analysis?

    Also detects hierarchical relationships (region > venue > product) and
    cross-segmentations where column interactions produce unique patterns.

    Args:
        dataset_id: Name of a previously loaded dataset
        timestamp_col: Which column is the timestamp
        value_cols: Which numeric columns matter (null = all numeric)
        min_segment_size: Minimum rows per segment to be viable (default: 50)
        max_segments: Maximum number of segments to suggest (default: 30)
    """
    result = run_suggest_segments(
        dataset_id=dataset_id,
        timestamp_col=timestamp_col,
        value_cols=value_cols,
        min_segment_size=min_segment_size,
        max_segments=max_segments,
    )
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def create_segments(
    dataset_id: str,
    segment_by: str | list[str],
    timestamp_col: str,
    value_cols: list[str] | None = None,
    min_segment_size: int = 50,
    export_format: str | None = None,
    export_dir: str | None = None,
) -> str:
    """
    Split data into segments based on column(s). Creates materialized DuckDB
    tables for each segment and optionally exports as files for Layer 1.

    Args:
        dataset_id: Name of a previously loaded dataset
        segment_by: Column(s) to segment on (string or list of strings)
        timestamp_col: Column containing timestamps
        value_cols: Columns to include (null = all numeric + timestamp)
        min_segment_size: Drop segments smaller than this (default: 50)
        export_format: 'csv' or 'parquet' (null = no export, keep in DuckDB only)
        export_dir: Directory for exported files
    """
    result = run_create_segments(
        dataset_id=dataset_id,
        segment_by=segment_by,
        timestamp_col=timestamp_col,
        value_cols=value_cols,
        min_segment_size=min_segment_size,
        export_format=export_format,
        export_dir=export_dir,
    )
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def list_segments(dataset_name: str, column: str) -> str:
    """
    List unique values and their counts for a column in a loaded dataset.
    Useful for exploring segment dimensions (e.g., store_id, product, region).

    Args:
        dataset_name: Name of a previously loaded dataset
        column: Column name to segment by
    """
    result = run_list_segments(dataset_name=dataset_name, column=column)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def export_segment(
    dataset_id: str,
    segment_id: str | None = None,
    fmt: str = "csv",
    output_dir: str = ".",
) -> str:
    """
    Export a specific segment (or all segments for a dataset) to files
    that Layer 1 can consume.

    Args:
        dataset_id: Name of a previously loaded dataset
        segment_id: Specific segment to export (null = all segments for this dataset)
        fmt: Export format: 'csv' or 'parquet' (default: 'csv')
        output_dir: Directory for exported files
    """
    result = run_export_segment(
        dataset_id=dataset_id,
        segment_id=segment_id,
        fmt=fmt,
        output_dir=output_dir,
    )
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def clean_dataset(
    dataset_id: str,
    operations: list[dict] | None = None,
    auto_detect: bool = True,
    apply: bool = False,
) -> str:
    """
    Detect and fix data quality issues in a loaded dataset.

    Two modes:
      Plan mode (default): auto-detect issues and return suggested fixes.
      Apply mode: execute provided cleaning operations.

    Detects: whitespace/case inconsistencies, fuzzy duplicate entity names,
    timezone issues, numeric values stored as strings, high null rates.

    Call with auto_detect=True first to see the plan, then with
    apply=True and the operations you want to execute.

    Args:
        dataset_id: Name of a previously loaded dataset
        operations: List of cleaning operations to apply (for apply mode)
        auto_detect: Scan for issues and suggest fixes (default True)
        apply: If True, apply the operations; if False, return plan only
    """
    result = run_clean_dataset(
        dataset_id=dataset_id,
        operations=operations,
        auto_detect=auto_detect,
        apply=apply,
    )
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def resolve_entities(
    dataset_id: str,
    column: str,
    context: str | None = None,
    model: str = "claude-sonnet-4-20250514",
) -> str:
    """
    Use LLM to resolve messy entity names in a categorical column.

    Sends all distinct values to Claude and asks it to group them into
    canonical entities. Handles semantic equivalence that fuzzy matching
    misses: abbreviations, packaging variants, regional naming differences.

    Only works for columns with <=200 distinct values. Returns a mapping
    and a ready-to-apply operation.

    Args:
        dataset_id: Name of a previously loaded dataset
        column: Categorical column to resolve
        context: Optional description of what this column represents
            (e.g. "beer brand names" or "venue locations")
        model: Anthropic model to use (default: claude-sonnet-4-20250514)
    """
    result = run_llm_entity_resolution(
        dataset_id=dataset_id,
        column=column,
        context=context,
        model=model,
    )
    return json.dumps(result, indent=2, default=str)


def main():
    """Run the MCP server via stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
