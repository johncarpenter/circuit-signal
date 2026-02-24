"""
Signal Correlation MCP Server (Layer 2)

Cross-dataset signal correlation. Ingests typed signals from Layer 1
instances and discovers temporal, spatial, and entity-level alignments
that surface commercial insights no single dataset can reveal.

Tools:
  1. register_source  — declare a data source and its semantic context
  2. list_sources     — list registered sources with signal counts
  3. ingest_signals   — parse Layer 1 output into canonical signal store
  4. correlate_signals — run cross-source correlation analysis
  5. query_insights   — retrieve and filter discovered insights
  6. explain_insight  — deep-dive into a specific insight with full evidence chain
"""

import json
import logging

from mcp.server.fastmcp import FastMCP

from signal_correlation.store import SignalStore
from signal_correlation.tools.sources import run_register_source, run_list_sources
from signal_correlation.tools.ingest import run_ingest_signals
from signal_correlation.tools.correlate import run_correlate_signals
from signal_correlation.tools.insights import run_query_insights, run_explain_insight

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("signal-correlation")

mcp = FastMCP(
    "Signal Correlation",
    instructions=(
        "Cross-dataset signal correlation engine (Layer 2). "
        "Finds temporal, spatial, and entity-level alignments across "
        "signals from multiple Layer 1 instances."
    ),
)

# Shared store instance — persists across tool calls within a session
_store: SignalStore | None = None


def _get_store(db_path: str | None = None) -> SignalStore:
    global _store
    if _store is None:
        _store = SignalStore(db_path=db_path)
    return _store


# ---------------------------------------------------------------------------
# Tool 1: register_source
# ---------------------------------------------------------------------------
@mcp.tool()
def register_source(
    source_id: str,
    name: str,
    description: str | None = None,
    domain: str = "other",
    geography: dict | None = None,
    entity_keys: list[str] | None = None,
    baseline_path: str | None = None,
    tags: list[str] | None = None,
    db_path: str | None = None,
) -> str:
    """
    Register a data source that feeds signals into the correlation engine.
    Describes what this data source represents semantically — domain, geography,
    shared entity keys — so correlations are meaningful.

    Args:
        source_id: Unique identifier (e.g. 'edinburgh_pos', 'jwps_bookings')
        name: Human-readable name
        description: What this data source represents
        domain: Source domain: 'pos','bookings','web_analytics','social','weather','events','retail','crm','other'
        geography: Location context: {region, latitude, longitude, radius_km}
        entity_keys: Shared identifier columns (e.g. ['customer_id','venue_id'])
        baseline_path: Path to Layer 1 baseline artifacts for this source
        tags: Freeform tags for filtering (e.g. ['whisky','premium','scotland'])
        db_path: Custom path for the signal store database
    """
    store = _get_store(db_path)
    result = run_register_source(
        store=store, source_id=source_id, name=name,
        description=description, domain=domain, geography=geography,
        entity_keys=entity_keys, baseline_path=baseline_path, tags=tags,
    )
    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 2: list_sources
# ---------------------------------------------------------------------------
@mcp.tool()
def list_sources(
    db_path: str | None = None,
) -> str:
    """
    List all registered data sources with their signal counts and metadata.

    Args:
        db_path: Custom path for the signal store database
    """
    store = _get_store(db_path)
    result = run_list_sources(store)
    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 3: ingest_signals
# ---------------------------------------------------------------------------
@mcp.tool()
def ingest_signals(
    source_id: str,
    signal_type: str = "deviations",
    data: dict | None = None,
    data_path: str | None = None,
    context: dict | None = None,
    db_path: str | None = None,
) -> str:
    """
    Ingest Layer 1 output (Mode 1 baselines or Mode 2 deviations) into
    the correlation store. Normalizes signals into a canonical format
    for cross-source analysis.

    Provide either 'data' (direct JSON) or 'data_path' (file path to
    Layer 1 output JSON).

    Args:
        source_id: Must match a registered source
        signal_type: Type of Layer 1 output: 'deviations' (Mode 2) or 'baseline' (Mode 1)
        data: Direct Layer 1 output JSON object
        data_path: Path to Layer 1 output JSON file
        context: Optional context: {analysis_timestamp, data_window: {start, end}}
        db_path: Custom path for the signal store database
    """
    store = _get_store(db_path)
    result = run_ingest_signals(
        store=store, source_id=source_id, signal_type=signal_type,
        data=data, data_path=data_path, context=context,
    )
    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 4: correlate_signals
# ---------------------------------------------------------------------------
@mcp.tool()
def correlate_signals(
    source_ids: list[str] | None = None,
    time_window: dict | None = None,
    correlation_types: list[str] | None = None,
    options: dict | None = None,
    db_path: str | None = None,
) -> str:
    """
    Run cross-source signal correlation analysis. Finds temporal co-occurrences,
    lagged relationships, spatial alignments, entity-level matches, and
    seasonal pattern similarities. Groups findings into actionable insight clusters.

    Args:
        source_ids: Sources to correlate (null = all registered)
        time_window: Filter signals: {start: ISO, end: ISO}
        correlation_types: Methods to run: 'temporal_co_occurrence','lagged_correlation',
            'spatial_alignment','entity_alignment','pattern_similarity' (null = all)
        options: Tuning parameters:
            temporal_window: max gap for co-occurrence (default '7d')
            spatial_radius_km: max distance for spatial match (default 50.0)
            lag_max_periods: max lag to scan (default 30)
            min_confidence: minimum confidence to report (default 0.5)
            cluster_signals: group into insight clusters (default true)
        db_path: Custom path for the signal store database
    """
    store = _get_store(db_path)
    result = run_correlate_signals(
        store=store, source_ids=source_ids, time_window=time_window,
        correlation_types=correlation_types, options=options,
    )
    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 5: query_insights
# ---------------------------------------------------------------------------
@mcp.tool()
def query_insights(
    source_ids: list[str] | None = None,
    min_actionability: float = 0.0,
    min_strength: float = 0.0,
    tags: list[str] | None = None,
    time_window: dict | None = None,
    limit: int = 20,
    sort_by: str = "actionability",
    db_path: str | None = None,
) -> str:
    """
    Retrieve and filter previously discovered insights.

    Args:
        source_ids: Filter to insights involving these sources
        min_actionability: Minimum actionability score (0-1, default 0.0)
        min_strength: Minimum correlation strength (0-1, default 0.0)
        tags: Filter by source tags
        time_window: Filter by time: {start: ISO, end: ISO}
        limit: Max results (default 20)
        sort_by: Sort order: 'actionability','strength','recency' (default 'actionability')
        db_path: Custom path for the signal store database
    """
    store = _get_store(db_path)
    result = run_query_insights(
        store=store, source_ids=source_ids,
        min_actionability=min_actionability, min_strength=min_strength,
        tags=tags, time_window=time_window, limit=limit, sort_by=sort_by,
    )
    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 6: explain_insight
# ---------------------------------------------------------------------------
@mcp.tool()
def explain_insight(
    insight_id: str,
    db_path: str | None = None,
) -> str:
    """
    Deep-dive into a specific insight. Returns the full signal chain,
    correlation evidence, confidence assessment with weakest-link analysis,
    alternative explanations, and actionability reasoning.

    Args:
        insight_id: The insight ID to explain
        db_path: Custom path for the signal store database
    """
    store = _get_store(db_path)
    result = run_explain_insight(store=store, insight_id=insight_id)
    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    """Run the MCP server via stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
