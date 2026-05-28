"""MCP Gateway — exposes signal-query tools over MCP SSE transport."""

import asyncio
import json
import logging

from mcp.server.fastmcp import FastMCP

from circuit_mcp.config import config
from circuit_mcp.db import async_session
from circuit_mcp.query import (
    SearchAxis,
    find_similar_by_signal,
    find_similar_by_text,
    explain_similarity,
    cluster_signals,
    store_statistics,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("Circuit Signal", host="0.0.0.0", port=config.MCP_PORT)


@mcp.tool()
async def find_similar(
    signal_id: str | None = None,
    query: str | None = None,
    axis: str = "shape",
    limit: int = 10,
    dataset_filter: str | None = None,
) -> str:
    """Find signals similar to a given signal or text query.

    Args:
        signal_id: Find signals similar to this signal (by embedding distance)
        query: Natural language query (text search fallback)
        axis: Embedding axis to search on: "shape", "deviation", or "text"
        limit: Maximum results to return (default 10)
        dataset_filter: Restrict to a specific dataset name
    """
    search_axis = SearchAxis(axis)

    async with async_session() as db:
        if signal_id:
            results = await find_similar_by_signal(
                db=db,
                signal_id=signal_id,
                axis=search_axis,
                limit=limit,
                dataset_filter=dataset_filter,
            )
            return json.dumps({"results": results, "search_type": "signal_similarity", "axis": axis}, default=str)

        if query:
            # Text fallback — use ILIKE search (embedding search requires text encoder)
            from sqlalchemy import text as sql_text
            stmt = sql_text("""
                SELECT signal_id, dataset_name, segment, segment_by,
                       text_description, trend_slope, seasonality_strength, deviation_count_90d
                FROM signals
                WHERE status = 'active' AND text_description ILIKE :pattern
                LIMIT :limit
            """)
            result = await db.execute(stmt, {"pattern": f"%{query}%", "limit": limit})
            rows = result.fetchall()
            results = [
                {
                    "signal_id": r.signal_id,
                    "dataset_name": r.dataset_name,
                    "segment": r.segment,
                    "text_description": r.text_description,
                }
                for r in rows
            ]
            return json.dumps({"results": results, "search_type": "text_search"}, default=str)

        return json.dumps({"error": "Provide either signal_id or query"})


@mcp.tool()
async def get_signal(signal_id: str) -> str:
    """Get full details for a specific signal by its signal_id.

    Args:
        signal_id: The signal identifier (format: dataset:segment:run_id)
    """
    from sqlalchemy import text as sql_text

    async with async_session() as db:
        result = await db.execute(
            sql_text("""
                SELECT signal_id, dataset_name, segment, segment_by, temporal_grain,
                       row_count, tags, trend_slope, trend_intercept, seasonality_strength,
                       residual_std, deviation_count_90d, deviation_density, critical_pct,
                       change_points, text_description, status, superseded_by, registered_at
                FROM signals WHERE signal_id = :sid
            """),
            {"sid": signal_id},
        )
        row = result.fetchone()
        if not row:
            return json.dumps({"error": f"Signal '{signal_id}' not found"})

        return json.dumps({
            "signal_id": row.signal_id,
            "dataset_name": row.dataset_name,
            "segment": row.segment,
            "segment_by": row.segment_by,
            "temporal_grain": row.temporal_grain,
            "row_count": row.row_count,
            "tags": row.tags,
            "trend_slope": row.trend_slope,
            "trend_intercept": row.trend_intercept,
            "seasonality_strength": row.seasonality_strength,
            "residual_std": row.residual_std,
            "deviation_count_90d": row.deviation_count_90d,
            "deviation_density": row.deviation_density,
            "critical_pct": row.critical_pct,
            "change_points": row.change_points,
            "text_description": row.text_description,
            "status": row.status,
            "registered_at": str(row.registered_at),
        }, default=str)


@mcp.tool()
async def list_signals(
    dataset_name: str | None = None,
    segment_by: str | None = None,
    status: str = "active",
    limit: int = 50,
) -> str:
    """Browse signals in the store with optional filters.

    Args:
        dataset_name: Filter by dataset name
        segment_by: Filter by segmentation column
        status: Filter by status (default: "active")
        limit: Maximum results (default 50, max 200)
    """
    from sqlalchemy import text as sql_text

    where_parts = ["status = :status"]
    params: dict = {"status": status, "limit": min(limit, 200)}

    if dataset_name:
        where_parts.append("dataset_name = :dataset_name")
        params["dataset_name"] = dataset_name
    if segment_by:
        where_parts.append("segment_by = :segment_by")
        params["segment_by"] = segment_by

    where_sql = " AND ".join(where_parts)

    async with async_session() as db:
        result = await db.execute(
            sql_text(f"""
                SELECT signal_id, dataset_name, segment, segment_by, temporal_grain,
                       trend_slope, seasonality_strength, deviation_count_90d,
                       text_description, registered_at
                FROM signals
                WHERE {where_sql}
                ORDER BY registered_at DESC
                LIMIT :limit
            """),
            params,
        )
        rows = result.fetchall()
        signals = [
            {
                "signal_id": r.signal_id,
                "dataset_name": r.dataset_name,
                "segment": r.segment,
                "segment_by": r.segment_by,
                "temporal_grain": r.temporal_grain,
                "trend_slope": r.trend_slope,
                "seasonality_strength": r.seasonality_strength,
                "deviation_count_90d": r.deviation_count_90d,
                "text_description": r.text_description,
                "registered_at": str(r.registered_at),
            }
            for r in rows
        ]
        return json.dumps({"signals": signals, "count": len(signals)}, default=str)


@mcp.tool()
async def explain_signal_similarity(signal_id_a: str, signal_id_b: str) -> str:
    """Compare two signals and explain their similarity across all embedding axes.

    Args:
        signal_id_a: First signal identifier
        signal_id_b: Second signal identifier
    """
    async with async_session() as db:
        result = await explain_similarity(db, signal_id_a, signal_id_b)
        return json.dumps(result, default=str)


@mcp.tool()
async def discover_clusters(
    axis: str = "shape",
    n_clusters: int = 5,
    dataset_filter: str | None = None,
) -> str:
    """Discover signal clusters (occasion archetypes) using embedding similarity.

    Args:
        axis: Embedding axis for clustering: "shape", "deviation", or "text"
        n_clusters: Number of clusters to discover (default 5)
        dataset_filter: Restrict to signals from a specific dataset
    """
    search_axis = SearchAxis(axis)
    async with async_session() as db:
        clusters = await cluster_signals(
            db=db,
            axis=search_axis,
            n_clusters=n_clusters,
            dataset_filter=dataset_filter,
        )
        return json.dumps({"clusters": clusters, "axis": axis}, default=str)


@mcp.tool()
async def store_stats() -> str:
    """Get summary statistics for the signal store."""
    async with async_session() as db:
        stats = await store_statistics(db)
        return json.dumps(stats, default=str)


@mcp.tool()
async def list_deviations(
    dataset_name: str | None = None,
    segment: str | None = None,
    severity: str | None = None,
    deviation_type: str | None = None,
    signal_id: str | None = None,
    limit: int = 50,
) -> str:
    """List individual deviation records with optional filters.

    Use this to find advertising/buying opportunities — deviations represent
    anomalous periods where demand diverged from the baseline pattern.

    Args:
        dataset_name: Filter by dataset name
        segment: Filter by segment (e.g. product, store, brand)
        severity: Filter by severity: "low", "medium", "high", "critical"
        deviation_type: Filter by type: "spike", "dip", "level_shift", "trend_break"
        signal_id: Filter by a specific signal_id
        limit: Maximum results (default 50, max 200)
    """
    from sqlalchemy import text as sql_text

    where_parts: list[str] = []
    params: dict = {"limit": min(limit, 200)}

    if dataset_name:
        where_parts.append("dataset_name = :dataset_name")
        params["dataset_name"] = dataset_name
    if segment:
        where_parts.append("segment = :segment")
        params["segment"] = segment
    if severity:
        where_parts.append("severity = :severity")
        params["severity"] = severity
    if deviation_type:
        where_parts.append("deviation_type = :deviation_type")
        params["deviation_type"] = deviation_type
    if signal_id:
        where_parts.append("signal_id = :signal_id")
        params["signal_id"] = signal_id

    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    async with async_session() as db:
        result = await db.execute(
            sql_text(f"""
                SELECT id, signal_id, dataset_name, segment, segment_by,
                       column_name, deviation_type, severity, persistence,
                       timestamp_start, timestamp_end,
                       expected_value, observed_value, deviation_magnitude,
                       z_score, confidence, narrative
                FROM deviations
                {where_sql}
                ORDER BY severity DESC, timestamp_start DESC
                LIMIT :limit
            """),
            params,
        )
        rows = result.fetchall()
        deviations = [
            {
                "id": str(r.id),
                "signal_id": r.signal_id,
                "dataset_name": r.dataset_name,
                "segment": r.segment,
                "segment_by": r.segment_by,
                "column_name": r.column_name,
                "deviation_type": r.deviation_type,
                "severity": r.severity,
                "persistence": r.persistence,
                "timestamp_start": str(r.timestamp_start),
                "timestamp_end": str(r.timestamp_end),
                "expected_value": r.expected_value,
                "observed_value": r.observed_value,
                "deviation_magnitude": r.deviation_magnitude,
                "z_score": r.z_score,
                "confidence": r.confidence,
                "narrative": r.narrative,
            }
            for r in rows
        ]
        return json.dumps({"deviations": deviations, "count": len(deviations)}, default=str)


@mcp.tool()
async def summarize_deviations(
    dataset_name: str | None = None,
) -> str:
    """Get aggregate deviation statistics — severity distribution, top segments, type breakdown.

    Useful for a quick overview of where the biggest anomalies are across
    the signal store.

    Args:
        dataset_name: Restrict summary to a specific dataset
    """
    from sqlalchemy import text as sql_text

    dataset_filter = ""
    params: dict = {}
    if dataset_name:
        dataset_filter = "WHERE dataset_name = :dataset_name"
        params["dataset_name"] = dataset_name

    async with async_session() as db:
        # Total count
        total_result = await db.execute(
            sql_text(f"SELECT COUNT(*) AS cnt FROM deviations {dataset_filter}"),
            params,
        )
        total = total_result.scalar()

        # By severity
        sev_result = await db.execute(
            sql_text(f"""
                SELECT severity, COUNT(*) AS cnt
                FROM deviations {dataset_filter}
                GROUP BY severity ORDER BY cnt DESC
            """),
            params,
        )
        by_severity = {r.severity: r.cnt for r in sev_result.fetchall()}

        # By type
        type_result = await db.execute(
            sql_text(f"""
                SELECT deviation_type, COUNT(*) AS cnt
                FROM deviations {dataset_filter}
                GROUP BY deviation_type ORDER BY cnt DESC
            """),
            params,
        )
        by_type = {r.deviation_type: r.cnt for r in type_result.fetchall()}

        # Top segments by deviation count
        seg_result = await db.execute(
            sql_text(f"""
                SELECT dataset_name, segment, COUNT(*) AS cnt
                FROM deviations {dataset_filter}
                GROUP BY dataset_name, segment
                ORDER BY cnt DESC LIMIT 10
            """),
            params,
        )
        top_segments = [
            {"dataset_name": r.dataset_name, "segment": r.segment, "count": r.cnt}
            for r in seg_result.fetchall()
        ]

        return json.dumps({
            "total_deviations": total,
            "by_severity": by_severity,
            "by_type": by_type,
            "top_segments": top_segments,
        }, default=str)


if __name__ == "__main__":
    mcp.run(transport="sse")
