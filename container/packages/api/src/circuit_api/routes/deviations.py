import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from circuit_api.db import get_db
from circuit_api.models.orm import Deviation

router = APIRouter()


@router.get("/signals/{signal_id}/deviations")
async def get_signal_deviations(
    signal_id: uuid.UUID,
    severity: str | None = None,
    deviation_type: str | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Get deviations for a specific signal (by signal UUID → signal_id string)."""
    from circuit_api.models.orm import Signal

    # Resolve UUID to signal_id string
    result = await db.execute(select(Signal.signal_id).where(Signal.id == signal_id))
    sid = result.scalar_one_or_none()
    if not sid:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Signal not found")

    query = select(Deviation).where(Deviation.signal_id == sid)
    if severity:
        query = query.where(Deviation.severity == severity)
    if deviation_type:
        query = query.where(Deviation.deviation_type == deviation_type)
    query = query.order_by(Deviation.timestamp_start.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    devs = result.scalars().all()
    return [_deviation_dict(d) for d in devs]


@router.get("/deviations")
async def list_deviations(
    dataset_name: str | None = None,
    segment: str | None = None,
    severity: str | None = None,
    deviation_type: str | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Browse deviations with filters — the retail 'what needs attention' query."""
    query = select(Deviation)
    if dataset_name:
        query = query.where(Deviation.dataset_name == dataset_name)
    if segment:
        query = query.where(Deviation.segment == segment)
    if severity:
        query = query.where(Deviation.severity == severity)
    if deviation_type:
        query = query.where(Deviation.deviation_type == deviation_type)
    query = query.order_by(Deviation.severity.desc(), Deviation.timestamp_start.desc())
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    devs = result.scalars().all()
    return [_deviation_dict(d) for d in devs]


@router.get("/deviations/summary")
async def deviation_summary(
    dataset_name: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Aggregate deviation stats — severity distribution, top segments, recent activity."""
    base = select(
        Deviation.severity,
        func.count().label("count"),
    )
    if dataset_name:
        base = base.where(Deviation.dataset_name == dataset_name)
    base = base.group_by(Deviation.severity)

    result = await db.execute(base)
    by_severity = {row.severity: row.count for row in result.fetchall()}

    # Top segments by deviation count
    seg_query = (
        select(
            Deviation.dataset_name,
            Deviation.segment,
            func.count().label("count"),
        )
        .group_by(Deviation.dataset_name, Deviation.segment)
        .order_by(func.count().desc())
        .limit(10)
    )
    if dataset_name:
        seg_query = seg_query.where(Deviation.dataset_name == dataset_name)

    result = await db.execute(seg_query)
    top_segments = [
        {"dataset_name": r.dataset_name, "segment": r.segment, "count": r.count}
        for r in result.fetchall()
    ]

    # Type distribution
    type_query = (
        select(
            Deviation.deviation_type,
            func.count().label("count"),
        )
        .group_by(Deviation.deviation_type)
    )
    if dataset_name:
        type_query = type_query.where(Deviation.dataset_name == dataset_name)

    result = await db.execute(type_query)
    by_type = {row.deviation_type: row.count for row in result.fetchall()}

    total = sum(by_severity.values())

    return {
        "total_deviations": total,
        "by_severity": by_severity,
        "by_type": by_type,
        "top_segments": top_segments,
    }


def _deviation_dict(d: Deviation) -> dict:
    return {
        "id": str(d.id),
        "signal_id": d.signal_id,
        "dataset_name": d.dataset_name,
        "segment": d.segment,
        "segment_by": d.segment_by,
        "column_name": d.column_name,
        "deviation_type": d.deviation_type,
        "severity": d.severity,
        "persistence": d.persistence,
        "timestamp_start": d.timestamp_start.isoformat(),
        "timestamp_end": d.timestamp_end.isoformat(),
        "expected_value": d.expected_value,
        "observed_value": d.observed_value,
        "deviation_magnitude": d.deviation_magnitude,
        "z_score": d.z_score,
        "confidence": d.confidence,
        "narrative": d.narrative,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }
