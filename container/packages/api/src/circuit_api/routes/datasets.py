import uuid

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from circuit_api.db import get_db
from circuit_api.models.orm import Dataset
from circuit_api.services.storage import storage

router = APIRouter()


@router.post("/datasets")
async def create_dataset(
    name: str,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload CSV(s) and create a dataset."""
    dataset_id = uuid.uuid4()
    file_refs = []

    for f in files:
        data = await f.read()
        key = f"uploads/{dataset_id}/{f.filename}"
        await storage.upload_file(key, data, content_type=f.content_type or "application/octet-stream")
        file_refs.append({
            "filename": f.filename,
            "content_type": f.content_type,
            "size_bytes": len(data),
            "key": key,
        })

    dataset = Dataset(
        id=dataset_id,
        name=name,
        status="uploaded",
        file_refs=file_refs,
    )
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)
    return {"id": str(dataset.id), "name": dataset.name, "status": dataset.status}


@router.get("/datasets")
async def list_datasets(db: AsyncSession = Depends(get_db)):
    """List all datasets."""
    result = await db.execute(
        select(Dataset).where(Dataset.deleted_at.is_(None)).order_by(Dataset.created_at.desc())
    )
    datasets = result.scalars().all()
    return [
        {"id": str(d.id), "name": d.name, "status": d.status, "created_at": d.created_at.isoformat()}
        for d in datasets
    ]


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get dataset detail with profile results."""
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return {
        "id": str(dataset.id),
        "name": dataset.name,
        "status": dataset.status,
        "file_refs": dataset.file_refs,
        "profile": dataset.profile,
        "config": dataset.config,
        "tags": dataset.tags,
        "created_at": dataset.created_at.isoformat(),
    }


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Soft-delete a dataset."""
    from datetime import datetime, timezone

    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    dataset.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "deleted"}


@router.post("/datasets/{dataset_id}/profile")
async def trigger_profile(dataset_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Trigger profiling for a dataset."""
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    dataset.status = "profiling"
    await db.commit()

    from circuit_api.services.tasks import enqueue_profile
    await enqueue_profile(str(dataset_id))

    return {"status": "profiling", "dataset_id": str(dataset_id)}


@router.patch("/datasets/{dataset_id}/config")
async def update_config(
    dataset_id: uuid.UUID,
    config: dict,
    db: AsyncSession = Depends(get_db),
):
    """Update analysis configuration for a dataset."""
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    dataset.config = config
    await db.commit()
    return {"status": "updated", "config": dataset.config}
