import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from circuit_api.db import get_db
from circuit_api.models.orm import AnalysisRun, Dataset

router = APIRouter()


@router.post("/datasets/{dataset_id}/analyze")
async def trigger_analysis(dataset_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Trigger an analysis run for a dataset."""
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    manifest = {}
    if dataset.config:
        manifest = dataset.config

    run = AnalysisRun(
        dataset_id=dataset_id,
        status="queued",
        manifest=manifest,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    from circuit_api.services.tasks import enqueue_analysis
    await enqueue_analysis(str(run.id))

    return {"run_id": str(run.id), "status": run.status}


@router.get("/runs")
async def list_runs(
    dataset_id: uuid.UUID | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List analysis runs, optionally filtered."""
    query = select(AnalysisRun).order_by(AnalysisRun.created_at.desc())
    if dataset_id:
        query = query.where(AnalysisRun.dataset_id == dataset_id)
    if status:
        query = query.where(AnalysisRun.status == status)
    result = await db.execute(query)
    runs = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "dataset_id": str(r.dataset_id),
            "status": r.status,
            "progress": r.progress,
            "created_at": r.created_at.isoformat(),
        }
        for r in runs
    ]


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get run detail with progress."""
    result = await db.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "id": str(run.id),
        "dataset_id": str(run.dataset_id),
        "status": run.status,
        "manifest": run.manifest,
        "progress": run.progress,
        "result_refs": run.result_refs,
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat(),
    }


@router.get("/runs/{run_id}/report")
async def get_report(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get the markdown report for a completed run."""
    result = await db.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "completed":
        raise HTTPException(status_code=400, detail=f"Run is not completed (status: {run.status})")

    from circuit_api.services.storage import storage

    # Try to find report in MinIO
    report_key = f"results/{run_id}/report.md"
    try:
        data = await storage.download_file(report_key)
        return Response(content=data, media_type="text/markdown")
    except Exception:
        # Try batch_summary.json as fallback
        summary_key = f"results/{run_id}/batch_summary.json"
        try:
            data = await storage.download_file(summary_key)
            return Response(content=data, media_type="application/json")
        except Exception:
            raise HTTPException(status_code=404, detail="Report not found")


@router.get("/runs/{run_id}/charts/{chart_name}")
async def get_chart(run_id: uuid.UUID, chart_name: str, db: AsyncSession = Depends(get_db)):
    """Proxy a chart image from MinIO."""
    result = await db.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    from circuit_api.services.storage import storage

    # Ensure chart_name doesn't contain path traversal
    if "/" in chart_name or ".." in chart_name:
        raise HTTPException(status_code=400, detail="Invalid chart name")

    chart_key = f"results/{run_id}/charts/{chart_name}"
    try:
        data = await storage.download_file(chart_key)
        media_type = "image/png" if chart_name.endswith(".png") else "application/octet-stream"
        return Response(content=data, media_type=media_type)
    except Exception:
        raise HTTPException(status_code=404, detail="Chart not found")


@router.get("/runs/{run_id}/segments")
async def list_segments(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """List segments for a run with summary stats from registered signals."""
    from sqlalchemy import text

    result = await db.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Get signals registered for this run
    signals_result = await db.execute(
        text("""
            SELECT signal_id, segment, segment_by, temporal_grain,
                   row_count, trend_slope, seasonality_strength,
                   deviation_count_90d, deviation_density, critical_pct,
                   text_description, status
            FROM signals
            WHERE run_id = :run_id
            ORDER BY segment
        """),
        {"run_id": str(run_id)},
    )

    segments = [
        {
            "signal_id": r.signal_id,
            "segment": r.segment,
            "segment_by": r.segment_by,
            "temporal_grain": r.temporal_grain,
            "row_count": r.row_count,
            "trend_slope": r.trend_slope,
            "seasonality_strength": r.seasonality_strength,
            "deviation_count_90d": r.deviation_count_90d,
            "deviation_density": r.deviation_density,
            "critical_pct": r.critical_pct,
            "text_description": r.text_description,
            "status": r.status,
        }
        for r in signals_result.fetchall()
    ]

    return {
        "run_id": str(run_id),
        "total_segments": len(segments),
        "segments": segments,
    }
