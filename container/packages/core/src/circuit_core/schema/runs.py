"""Run configuration and status models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DatasetStatus(str, Enum):
    UPLOADED = "uploaded"
    PROFILING = "profiling"
    PROFILED = "profiled"
    ERROR = "error"


class RunStatusEnum(str, Enum):
    QUEUED = "queued"
    PROFILING = "profiling"
    ANALYZING = "analyzing"
    REPORTING = "reporting"
    REGISTERING = "registering"
    COMPLETED = "completed"
    FAILED = "failed"


class DatasetCreate(BaseModel):
    """Request to create a new dataset."""

    name: str
    created_by: str | None = None
    tags: dict = Field(default_factory=dict)


class DatasetResponse(BaseModel):
    """Dataset summary response."""

    id: uuid.UUID
    name: str
    status: DatasetStatus
    file_refs: list[dict]
    profile: dict | None = None
    config: dict | None = None
    tags: dict = Field(default_factory=dict)
    created_at: datetime


class RunConfig(BaseModel):
    """Configuration for an analysis run."""

    dataset_id: uuid.UUID
    segmentation_column: str | None = None
    segmentation_level: str | None = None  # brand, product, store, etc.
    sensitivity: float = 1.0
    lookback_days: int | None = None
    tags: dict = Field(default_factory=dict)


class RunStatus(BaseModel):
    """Analysis run status."""

    id: uuid.UUID
    dataset_id: uuid.UUID
    status: RunStatusEnum
    progress: dict = Field(default_factory=dict)
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
