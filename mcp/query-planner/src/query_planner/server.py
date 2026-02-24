"""
Query Planner MCP Server

Loads a TDV profiler graph.json and provides tools for dataset discovery,
join path resolution, plan building, and temporal-aware plan execution.

Tools:
  1. load_graph      — load graph.json into memory, return summary
  2. graph_summary   — return datasets, discriminators, hierarchies
  3. find_datasets   — find datasets for a value, traverse CHILD_OF edges
  4. find_join_path  — find shared discriminators or hierarchy bridge
  5. build_plan      — build a DataPlan (value mode or dataset mode)
  6. execute_plan    — execute plan with ASOF joins, export CSV/Parquet
"""

import json
import logging

from mcp.server.fastmcp import FastMCP

from query_planner.engine import QueryEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("query-planner")

mcp = FastMCP(
    "Query Planner",
    instructions=(
        "TDV graph query planner. Loads a pre-computed graph from the TDV profiler, "
        "discovers relevant datasets, resolves join paths, builds structured plans, "
        "and executes temporal-aware joins (ASOF for grain mismatches)."
    ),
)

# Shared engine instance — persists across tool calls within a session
_engine: QueryEngine | None = None


def _get_engine() -> QueryEngine:
    global _engine
    if _engine is None:
        _engine = QueryEngine()
    return _engine


# ---------------------------------------------------------------------------
# Tool 1: load_graph
# ---------------------------------------------------------------------------
@mcp.tool()
def load_graph(graph_path: str) -> str:
    """
    Load a TDV profiler graph.json into memory. Returns a summary of
    datasets, discriminators, and hierarchies found in the graph.

    Args:
        graph_path: Path to the graph.json file produced by tdv-profiler
    """
    engine = _get_engine()
    result = engine.load_graph(graph_path)
    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 2: graph_summary
# ---------------------------------------------------------------------------
@mcp.tool()
def graph_summary() -> str:
    """
    Return the full summary of the loaded graph including all datasets,
    discriminators, hierarchies, and node/edge counts.
    """
    engine = _get_engine()
    result = engine.get_summary()
    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 3: find_datasets
# ---------------------------------------------------------------------------
@mcp.tool()
def find_datasets(
    value: str,
    discriminator_col: str | None = None,
) -> str:
    """
    Find datasets containing a specific value (e.g. "Bud Light"),
    traversing CHILD_OF edges to discover hierarchical matches.

    Args:
        value: The discriminator value to search for
        discriminator_col: Optional column name to restrict the search to
    """
    engine = _get_engine()
    result = engine.find_datasets(value, discriminator_col)
    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 4: find_join_path
# ---------------------------------------------------------------------------
@mcp.tool()
def find_join_path(
    dataset_a: str,
    dataset_b: str,
) -> str:
    """
    Find how two datasets can be joined — via shared discriminators
    (direct join) or via a hierarchy bridge (hierarchical join).

    Args:
        dataset_a: First dataset ID
        dataset_b: Second dataset ID
    """
    engine = _get_engine()
    result = engine.find_join_path(dataset_a, dataset_b)
    if result is None:
        result = {"error": f"No join path between '{dataset_a}' and '{dataset_b}'"}
    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 5: build_plan
# ---------------------------------------------------------------------------
@mcp.tool()
def build_plan(
    target_value: str | None = None,
    dataset_ids: list[str] | None = None,
    target_discriminator: str | None = None,
) -> str:
    """
    Build a DataPlan for joining datasets.

    Value mode: provide target_value to auto-discover datasets containing
    that value, pick the richest as primary, and find supplementary joins.

    Dataset mode: provide dataset_ids where the first is primary and the
    rest are supplementary with auto-discovered join keys.

    Args:
        target_value: A discriminator value to build a plan around
        dataset_ids: Explicit list of dataset IDs (first = primary)
        target_discriminator: Optional column to restrict value search
    """
    engine = _get_engine()
    result = engine.build_plan(
        target_value=target_value,
        dataset_ids=dataset_ids,
        target_discriminator=target_discriminator,
    )
    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 6: execute_plan
# ---------------------------------------------------------------------------
@mcp.tool()
def execute_plan(
    output_path: str,
    export_format: str = "csv",
) -> str:
    """
    Execute the most recently built plan. Loads datasets, applies filters,
    joins supplementary datasets (equi-join for same grain, ASOF for
    different grains), and exports the result.

    Args:
        output_path: File path to write the output
        export_format: Output format: 'csv' or 'parquet' (default: 'csv')
    """
    engine = _get_engine()
    result = engine.execute_plan(output_path, export_format)
    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    """Run the MCP server via stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
