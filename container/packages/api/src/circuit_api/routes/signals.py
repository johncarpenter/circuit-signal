import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from circuit_api.db import get_db
from circuit_api.models.orm import Signal
from circuit_api.services.query import (
    SearchAxis,
    find_similar_by_signal,
    find_similar_by_text,
    explain_similarity,
    cluster_signals,
    store_statistics,
)

router = APIRouter()


@router.get("/signals")
async def list_signals(
    dataset_name: str | None = None,
    segment_by: str | None = None,
    status: str = "active",
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List signals with optional filters."""
    query = select(Signal).where(Signal.status == status)
    if dataset_name:
        query = query.where(Signal.dataset_name == dataset_name)
    if segment_by:
        query = query.where(Signal.segment_by == segment_by)
    query = query.order_by(Signal.registered_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    signals = result.scalars().all()
    return [
        {
            "id": str(s.id),
            "signal_id": s.signal_id,
            "dataset_name": s.dataset_name,
            "segment": s.segment,
            "segment_by": s.segment_by,
            "temporal_grain": s.temporal_grain,
            "status": s.status,
            "trend_slope": s.trend_slope,
            "seasonality_strength": s.seasonality_strength,
            "deviation_count_90d": s.deviation_count_90d,
            "text_description": s.text_description,
            "registered_at": s.registered_at.isoformat(),
        }
        for s in signals
    ]


@router.get("/signals/{signal_id}")
async def get_signal(signal_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get full signal record."""
    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    return {
        "id": str(signal.id),
        "signal_id": signal.signal_id,
        "dataset_name": signal.dataset_name,
        "segment": signal.segment,
        "segment_by": signal.segment_by,
        "temporal_grain": signal.temporal_grain,
        "row_count": signal.row_count,
        "tags": signal.tags,
        "trend_slope": signal.trend_slope,
        "trend_intercept": signal.trend_intercept,
        "seasonality_strength": signal.seasonality_strength,
        "residual_std": signal.residual_std,
        "deviation_count_90d": signal.deviation_count_90d,
        "deviation_density": signal.deviation_density,
        "critical_pct": signal.critical_pct,
        "change_points": signal.change_points,
        "seasonal_weekly": signal.seasonal_weekly,
        "seasonal_hourly": signal.seasonal_hourly,
        "seasonal_monthly": signal.seasonal_monthly,
        "has_shape_embedding": signal.shape_embedding is not None,
        "has_deviation_embedding": signal.deviation_embedding is not None,
        "has_text_embedding": signal.text_embedding is not None,
        "text_description": signal.text_description,
        "status": signal.status,
        "superseded_by": signal.superseded_by,
        "registered_at": signal.registered_at.isoformat(),
    }


@router.get("/signals/{signal_id}/similar")
async def get_similar_signals(
    signal_id: uuid.UUID,
    axis: str = Query(default="shape"),
    limit: int = Query(default=10, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Find signals similar to a given signal."""
    # Resolve uuid to signal_id string
    result = await db.execute(select(Signal.signal_id).where(Signal.id == signal_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Signal not found")

    try:
        search_axis = SearchAxis(axis)
    except ValueError:
        search_axis = SearchAxis.SHAPE

    results = await find_similar_by_signal(
        db=db,
        signal_id=row,
        axis=search_axis,
        limit=limit,
    )
    return {"results": results, "axis": search_axis.value}


class SearchRequest(BaseModel):
    """Signal search request body."""
    query: str | None = None          # Natural language query
    signal_id: str | None = None      # Find similar to this signal
    axis: SearchAxis = SearchAxis.SHAPE
    dataset_filter: str | None = None
    limit: int = 10


@router.post("/signals/search")
async def search_signals(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Similarity search — by natural language or signal-to-signal.

    If `signal_id` is provided, finds similar signals using the specified axis.
    If `query` is provided, attempts text embedding search (pgvector), falls back to ILIKE.
    """
    if request.signal_id:
        results = await find_similar_by_signal(
            db=db,
            signal_id=request.signal_id,
            axis=request.axis,
            limit=request.limit,
            dataset_filter=request.dataset_filter,
        )
        return {"results": results, "search_type": "signal_similarity", "axis": request.axis.value}

    if request.query:
        # Try text embedding search first
        try:
            from circuit_api.services.text_encoder import encode_query
            query_embedding = encode_query(request.query)
            if query_embedding:
                results = await find_similar_by_text(
                    db=db,
                    query_embedding=query_embedding,
                    limit=request.limit,
                    dataset_filter=request.dataset_filter,
                )
                return {"results": results, "search_type": "semantic_search"}
        except Exception:
            pass  # Fall through to ILIKE

        # Fallback: text search using ILIKE
        stmt = select(Signal).where(
            Signal.status == "active",
            Signal.text_description.ilike(f"%{request.query}%"),
        )
        if request.dataset_filter:
            stmt = stmt.where(Signal.dataset_name == request.dataset_filter)
        stmt = stmt.limit(request.limit)
        result = await db.execute(stmt)
        signals = result.scalars().all()
        return {
            "results": [
                {
                    "signal_id": s.signal_id,
                    "dataset_name": s.dataset_name,
                    "segment": s.segment,
                    "segment_by": s.segment_by,
                    "text_description": s.text_description,
                    "trend_slope": s.trend_slope,
                    "seasonality_strength": s.seasonality_strength,
                    "deviation_count_90d": s.deviation_count_90d,
                }
                for s in signals
            ],
            "search_type": "text_search",
        }

    raise HTTPException(status_code=400, detail="Provide either 'query' or 'signal_id'")


class ExplainRequest(BaseModel):
    signal_id_a: str
    signal_id_b: str


@router.post("/signals/explain")
async def explain_signals(
    request: ExplainRequest,
    db: AsyncSession = Depends(get_db),
):
    """Explain similarity between two signals across all embedding axes."""
    result = await explain_similarity(db, request.signal_id_a, request.signal_id_b)
    return result


class ClusterRequest(BaseModel):
    axis: SearchAxis = SearchAxis.SHAPE
    n_clusters: int = 5
    dataset_filter: str | None = None


@router.post("/signals/cluster")
async def cluster(
    request: ClusterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Discover signal clusters (occasion archetypes)."""
    clusters = await cluster_signals(
        db=db,
        axis=request.axis,
        n_clusters=request.n_clusters,
        dataset_filter=request.dataset_filter,
    )
    return {"clusters": clusters, "axis": request.axis.value}


@router.get("/store/stats")
async def store_stats(db: AsyncSession = Depends(get_db)):
    """Comprehensive signal store statistics."""
    return await store_statistics(db)
