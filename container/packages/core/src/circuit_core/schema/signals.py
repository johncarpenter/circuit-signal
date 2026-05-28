"""Signal record models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SignalRecord(BaseModel):
    """A single signal in the store — decomposed time series with embeddings."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    signal_id: str  # {dataset}:{segment}:{run_id}
    dataset_id: uuid.UUID
    run_id: uuid.UUID

    # Source metadata
    dataset_name: str
    segment: str
    segment_by: str
    temporal_grain: str
    row_count: int | None = None
    tags: dict = Field(default_factory=dict)

    # Decomposed components
    trend_slope: float | None = None
    trend_intercept: float | None = None
    seasonal_weekly: list[float] | None = None  # 7 values
    seasonal_hourly: list[float] | None = None  # 24 values
    seasonal_monthly: list[float] | None = None  # 12 values
    seasonality_strength: float | None = None
    residual_std: float | None = None

    # Deviation summary
    deviation_count_90d: int | None = None
    deviation_density: float | None = None
    critical_pct: float | None = None
    change_points: list[dict] | None = None  # [{date, magnitude, direction}]

    # Text
    text_description: str | None = None

    # Lifecycle
    status: str = "active"
    superseded_by: str | None = None
    registered_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
