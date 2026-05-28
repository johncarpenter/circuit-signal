"""Pydantic models for the pipeline management API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# -- Stage / State tracking ---------------------------------------------------

class StageStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class StageState(BaseModel):
    status: StageStatus = StageStatus.pending
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class ProjectState(BaseModel):
    project_id: str
    data_dir: str
    output_dir: str
    created_at: datetime
    stages: dict[str, StageState] = Field(default_factory=lambda: {
        "profile": StageState(),
        "normalize": StageState(),
        "plan": StageState(),
        "manifest": StageState(),
        "run": StageState(),
    })


# -- Request models -----------------------------------------------------------

class CreateProjectRequest(BaseModel):
    data_dir: str = Field(..., description="Path to data directory (relative to workspace or absolute)")
    project_name: Optional[str] = Field(None, description="Custom project name (defaults to dir name)")


class ProfileRequest(BaseModel):
    recursive: bool = True


class NormalizeRequest(BaseModel):
    columns: Optional[list[str]] = Field(None, description="Columns to normalize (null = auto-detect from profile)")
    mode: str = Field("rules", description="Normalization mode: 'rules' or 'llm'")
    rules: Optional[dict] = Field(None, description="Classification rules (for rules mode)")
    rules_path: Optional[str] = Field(None, description="Path to rules JSON file")
    fuzzy_threshold: int = 80
    hierarchy_levels: Optional[list[str]] = None
    context: Optional[str] = Field(None, description="Domain context for LLM classification")
    skip_columns: Optional[list[str]] = None


class PlanRequest(BaseModel):
    dataset_ids: Optional[list[str]] = Field(None, description="Explicit dataset IDs (null = auto-select temporal)")
    target_value: Optional[str] = Field(None, description="Build plan around a discriminator value")
    target_discriminator: Optional[str] = Field(None, description="Restrict target_value search to this column")
    segment_by: Optional[list[str]] = Field(None, description="Discriminator columns to segment by (null = all)")


class ManifestRequest(BaseModel):
    timestamp_col: Optional[str] = None
    dataset_name: Optional[str] = None
    data_path: Optional[str] = None
    deviations: Optional[dict] = Field(None, description="Override deviation config: {lookback_window, sensitivity}")
    segment_by: Optional[list[str]] = Field(None, description="Override segment columns")


class ManifestEditRequest(BaseModel):
    edits: dict[str, Any] = Field(..., description="Partial manifest dict to merge")


class BatchRunRequest(BaseModel):
    max_workers: int = Field(default=2, ge=1, le=32, description="Worker processes (each ~1GB; default 2 for 4GB containers)")
    run_name: Optional[str] = Field(None, description="Custom run name (defaults to timestamp)")


class ReportRequest(BaseModel):
    prompt: Optional[str] = Field(None,
        description="Custom instructions for report focus")
    max_turns: int = Field(default=50, ge=1, le=200,
        description="Max SDK turns for report generation")


class RunChatRequest(BaseModel):
    message: str = Field(..., description="Question or instruction about the run data")
    session_id: Optional[str] = Field(None, description="Session ID for multi-turn conversation")
    max_turns: int = Field(default=25, ge=1, le=100)


class RunChatResponse(BaseModel):
    session_id: Optional[str] = None
    response: str = ""


# -- Response models ----------------------------------------------------------

class ProjectSummary(BaseModel):
    project_id: str
    data_dir: str
    created_at: datetime
    stages: dict[str, StageState]


class ProfileResponse(BaseModel):
    graph_path: str
    datasets: int
    discriminators: int
    hierarchies: int = 0
    scan_result: Optional[dict] = None


class NormalizeResponse(BaseModel):
    columns_normalized: int
    columns: dict[str, Any]


class PlanResponse(BaseModel):
    primary_dataset: Optional[dict] = None
    supplementary_datasets: list[dict] = Field(default_factory=list)
    normalization_sql: dict[str, str] = Field(default_factory=dict)
    segment_by: list[str] = Field(default_factory=list)
    segment_estimates: dict[str, int] = Field(default_factory=dict)


class ManifestResponse(BaseModel):
    manifest: dict[str, Any]


class BatchRunResponse(BaseModel):
    run_id: str
    run_dir: str
    task_id: str


class RunSummary(BaseModel):
    run_id: str
    run_dir: str
    dataset_name: Optional[str] = None
    scenarios_total: int = 0
    scenarios_completed: int = 0
    segments_total: int = 0
    baselines_succeeded: int = 0
    deviations_succeeded: int = 0
    errors: Optional[list[str]] = None
    duration_seconds: Optional[float] = None


class ReportResponse(BaseModel):
    report_path: str
    charts: list[str] = Field(default_factory=list)
    content: str = ""
    generated_at: Optional[datetime] = None


class TaskResponse(BaseModel):
    task_id: str
    status: str
    stage: Optional[str] = None
    project_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
