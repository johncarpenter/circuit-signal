import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Text, Integer, Float, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY, TSTZRANGE
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="uploaded")
    file_refs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    profile: Mapped[dict | None] = mapped_column(JSONB)
    config: Mapped[dict | None] = mapped_column(JSONB)
    tags: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)
    progress: Mapped[dict] = mapped_column(JSONB, default=dict)
    result_refs: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Deviation(Base):
    __tablename__ = "deviations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_id: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    dataset_name: Mapped[str] = mapped_column(Text, nullable=False)
    segment: Mapped[str] = mapped_column(Text, nullable=False)
    segment_by: Mapped[str] = mapped_column(Text, nullable=False)
    column_name: Mapped[str] = mapped_column(Text, nullable=False)
    deviation_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    persistence: Mapped[str | None] = mapped_column(Text)
    timestamp_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timestamp_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_value: Mapped[float | None] = mapped_column(Float)
    observed_value: Mapped[float | None] = mapped_column(Float)
    deviation_magnitude: Mapped[float | None] = mapped_column(Float)
    z_score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    narrative: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dataset_name: Mapped[str] = mapped_column(Text, nullable=False)
    segment: Mapped[str] = mapped_column(Text, nullable=False)
    segment_by: Mapped[str] = mapped_column(Text, nullable=False)
    temporal_grain: Mapped[str] = mapped_column(Text, nullable=False)
    time_range = mapped_column(TSTZRANGE, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[dict] = mapped_column(JSONB, default=dict)
    trend_slope: Mapped[float | None] = mapped_column(Float)
    trend_intercept: Mapped[float | None] = mapped_column(Float)
    seasonal_weekly = mapped_column(ARRAY(Float), nullable=True)
    seasonal_hourly = mapped_column(ARRAY(Float), nullable=True)
    seasonal_monthly = mapped_column(ARRAY(Float), nullable=True)
    seasonality_strength: Mapped[float | None] = mapped_column(Float)
    residual_std: Mapped[float | None] = mapped_column(Float)
    deviation_count_90d: Mapped[int | None] = mapped_column(Integer)
    deviation_density: Mapped[float | None] = mapped_column(Float)
    critical_pct: Mapped[float | None] = mapped_column(Float)
    change_points: Mapped[dict | None] = mapped_column(JSONB)
    shape_embedding = mapped_column(Vector(54), nullable=True)
    deviation_embedding = mapped_column(Vector(47), nullable=True)
    foundation_embedding = mapped_column(Vector(512), nullable=True)
    text_description: Mapped[str | None] = mapped_column(Text)
    text_embedding = mapped_column(Vector(384), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    superseded_by: Mapped[str | None] = mapped_column(Text)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
