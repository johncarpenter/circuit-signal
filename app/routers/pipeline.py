"""Pipeline management API — project lifecycle, staged data processing, and batch execution."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.pipeline import (
    BatchRunRequest,
    BatchRunResponse,
    CreateProjectRequest,
    ManifestEditRequest,
    ManifestRequest,
    ManifestResponse,
    NormalizeRequest,
    NormalizeResponse,
    PlanRequest,
    PlanResponse,
    ProfileRequest,
    ProfileResponse,
    ProjectState,
    ProjectSummary,
    ReportRequest,
    ReportResponse,
    RunChatRequest,
    RunChatResponse,
    RunSummary,
    TaskResponse,
)
from app.services import pipeline_service as svc
from app.services.task_manager import register_task
from app.services.task_registry import TaskRegistry
from app.utils.auth import verify_http_token

logger = logging.getLogger("agent.pipeline-router")

router = APIRouter(prefix="/api/pipeline", dependencies=[Depends(verify_http_token)])


# =============================================================================
# Projects
# =============================================================================

@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(req: CreateProjectRequest) -> ProjectState:
    try:
        return svc.create_project(req.data_dir, req.project_name)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    except FileExistsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/projects")
async def list_projects() -> list[ProjectSummary]:
    return [
        ProjectSummary(
            project_id=p.project_id,
            data_dir=p.data_dir,
            created_at=p.created_at,
            stages=p.stages,
        )
        for p in svc.list_projects()
    ]


@router.get("/projects/{project_id}")
async def get_project(project_id: str) -> ProjectState:
    try:
        return svc.get_project(project_id)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Project not found: {project_id}")


# =============================================================================
# Stage 1: Profile
# =============================================================================

@router.post("/projects/{project_id}/profile")
async def run_profile(project_id: str, req: ProfileRequest = ProfileRequest()) -> ProfileResponse:
    _assert_project_exists(project_id)
    try:
        result = await svc.run_profile(project_id, recursive=req.recursive)
        return ProfileResponse(**result)
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/projects/{project_id}/profile")
async def get_profile(project_id: str) -> dict:
    _assert_project_exists(project_id)
    result = svc.get_profile(project_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Profile not yet generated")
    return result


# =============================================================================
# Stage 2: Normalize
# =============================================================================

@router.post("/projects/{project_id}/normalize")
async def run_normalize(project_id: str, req: NormalizeRequest = NormalizeRequest()):
    state = _assert_project_exists(project_id)
    _assert_stage_completed(project_id, "profile", state)

    if req.mode == "llm":
        # LLM mode is slow — run as async task
        registry = TaskRegistry.get()
        info = registry.submit(
            coro=svc.run_normalize(
                project_id,
                columns=req.columns,
                mode=req.mode,
                rules=req.rules,
                rules_path=req.rules_path,
                fuzzy_threshold=req.fuzzy_threshold,
                hierarchy_levels=req.hierarchy_levels,
                context=req.context,
                skip_columns=req.skip_columns,
            ),
            stage="normalize",
            project_id=project_id,
            register_fn=register_task,
        )
        return TaskResponse(
            task_id=info.task_id,
            status=info.status,
            stage="normalize",
            project_id=project_id,
            started_at=info.started_at,
        )

    # Rules mode is fast — run synchronously
    try:
        result = await svc.run_normalize(
            project_id,
            columns=req.columns,
            mode=req.mode,
            rules=req.rules,
            rules_path=req.rules_path,
            fuzzy_threshold=req.fuzzy_threshold,
            hierarchy_levels=req.hierarchy_levels,
            context=req.context,
            skip_columns=req.skip_columns,
        )
        return NormalizeResponse(**result)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/projects/{project_id}/normalize")
async def get_normalize(project_id: str) -> dict:
    _assert_project_exists(project_id)
    result = svc.get_normalize(project_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Normalization not yet generated")
    return result


# =============================================================================
# Stage 3: Plan
# =============================================================================

@router.post("/projects/{project_id}/plan")
async def run_plan(project_id: str, req: PlanRequest = PlanRequest()) -> PlanResponse:
    state = _assert_project_exists(project_id)
    _assert_stage_completed(project_id, "profile", state)

    try:
        result = await svc.run_plan(
            project_id,
            dataset_ids=req.dataset_ids,
            target_value=req.target_value,
            target_discriminator=req.target_discriminator,
            segment_by=req.segment_by,
        )
        return PlanResponse(**result)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/projects/{project_id}/plan")
async def get_plan(project_id: str) -> PlanResponse:
    _assert_project_exists(project_id)
    result = svc.get_plan(project_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Plan not yet generated")
    return PlanResponse(**result)


# =============================================================================
# Stage 4: Manifest
# =============================================================================

@router.post("/projects/{project_id}/manifest")
async def run_manifest(project_id: str, req: ManifestRequest = ManifestRequest()) -> ManifestResponse:
    state = _assert_project_exists(project_id)
    _assert_stage_completed(project_id, "plan", state)

    try:
        result = await svc.run_manifest(
            project_id,
            timestamp_col=req.timestamp_col,
            dataset_name=req.dataset_name,
            data_path=req.data_path,
            deviations=req.deviations,
            segment_by=req.segment_by,
        )
        return ManifestResponse(manifest=result)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/projects/{project_id}/manifest")
async def get_manifest(project_id: str) -> ManifestResponse:
    _assert_project_exists(project_id)
    result = svc.get_manifest(project_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Manifest not yet generated")
    return ManifestResponse(manifest=result)


@router.put("/projects/{project_id}/manifest")
async def edit_manifest(project_id: str, req: ManifestEditRequest) -> ManifestResponse:
    _assert_project_exists(project_id)
    try:
        result = svc.edit_manifest(project_id, req.edits)
        return ManifestResponse(manifest=result)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Manifest not yet generated")


# =============================================================================
# Stage 5: Batch Run
# =============================================================================

@router.post("/projects/{project_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_batch(project_id: str, req: BatchRunRequest = BatchRunRequest()) -> TaskResponse:
    state = _assert_project_exists(project_id)
    _assert_stage_completed(project_id, "manifest", state)

    registry = TaskRegistry.get()
    info = registry.submit(
        coro=svc.run_batch_pipeline(
            project_id,
            max_workers=req.max_workers,
            run_name=req.run_name,
        ),
        stage="run",
        project_id=project_id,
        register_fn=register_task,
    )
    return TaskResponse(
        task_id=info.task_id,
        status=info.status,
        stage="run",
        project_id=project_id,
        started_at=info.started_at,
    )


@router.get("/projects/{project_id}/runs")
async def list_runs(project_id: str) -> list[dict]:
    _assert_project_exists(project_id)
    return svc.list_runs(project_id)


@router.get("/projects/{project_id}/runs/{run_id}")
async def get_run(project_id: str, run_id: str) -> RunSummary:
    _assert_project_exists(project_id)
    result = svc.get_run(project_id, run_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Run not found: {run_id}")
    return RunSummary(**result)


# =============================================================================
# Stage 6: Report
# =============================================================================

@router.post(
    "/projects/{project_id}/runs/{run_id}/report",
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_report(
    project_id: str, run_id: str, req: ReportRequest = ReportRequest(),
) -> TaskResponse:
    _assert_project_exists(project_id)
    # Validate run exists with batch_summary.json
    result = svc.get_run(project_id, run_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Run not found: {run_id}")

    registry = TaskRegistry.get()
    info = registry.submit(
        coro=svc.generate_report(
            project_id,
            run_id,
            max_turns=req.max_turns,
            prompt=req.prompt,
        ),
        stage="report",
        project_id=project_id,
        register_fn=register_task,
    )
    return TaskResponse(
        task_id=info.task_id,
        status=info.status,
        stage="report",
        project_id=project_id,
        started_at=info.started_at,
    )


@router.get("/projects/{project_id}/runs/{run_id}/report")
async def get_report(project_id: str, run_id: str) -> ReportResponse:
    _assert_project_exists(project_id)
    result = svc.get_report(project_id, run_id)
    if result is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"Report not yet generated for run: {run_id}",
        )
    return ReportResponse(**result)


# =============================================================================
# Chat
# =============================================================================

@router.post(
    "/projects/{project_id}/runs/{run_id}/chat",
    status_code=status.HTTP_202_ACCEPTED,
)
async def chat_with_run(
    project_id: str, run_id: str, req: RunChatRequest,
) -> TaskResponse:
    _assert_project_exists(project_id)
    result = svc.get_run(project_id, run_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Run not found: {run_id}")

    registry = TaskRegistry.get()
    info = registry.submit(
        coro=svc.chat_with_run(
            project_id,
            run_id,
            message=req.message,
            session_id=req.session_id,
            max_turns=req.max_turns,
        ),
        stage="chat",
        project_id=project_id,
        register_fn=register_task,
    )
    return TaskResponse(
        task_id=info.task_id,
        status=info.status,
        stage="chat",
        project_id=project_id,
        started_at=info.started_at,
    )


# =============================================================================
# Tasks
# =============================================================================

@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> TaskResponse:
    info = TaskRegistry.get().get_task(task_id)
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Task not found: {task_id}")
    return TaskResponse(**info.to_dict())


# =============================================================================
# Helpers
# =============================================================================

def _assert_project_exists(project_id: str) -> ProjectState:
    try:
        return svc.get_project(project_id)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Project not found: {project_id}")
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _assert_stage_completed(project_id: str, stage: str, state: ProjectState | None = None) -> None:
    if state is None:
        state = _assert_project_exists(project_id)
    if state.stages[stage].status.value != "completed":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Stage '{stage}' must be completed first (current: {state.stages[stage].status.value})",
        )
