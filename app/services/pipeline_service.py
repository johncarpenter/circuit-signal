"""Pipeline service — wraps PreparationPipeline and batch_runner for the API."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")

from app.config import settings
from app.models.pipeline import (
    ProjectState,
    StageState,
    StageStatus,
)

logger = logging.getLogger("agent.pipeline-service")

# Lazy imports for heavy dependencies (may not be installed outside Docker)
_PreparationPipeline = None
_PipelineConfig = None
_run_batch = None
_load_manifest = None


def _ensure_imports():
    """Lazy-import data_prep and batch_runner (only available when packages installed)."""
    global _PreparationPipeline, _PipelineConfig, _run_batch, _load_manifest
    if _PreparationPipeline is None:
        from data_prep.pipeline import PreparationPipeline, PipelineConfig
        _PreparationPipeline = PreparationPipeline
        _PipelineConfig = PipelineConfig
    if _run_batch is None:
        from batch_runner.runner import run_batch
        from batch_runner.manifest import load_manifest
        _run_batch = run_batch
        _load_manifest = load_manifest


def _make_llm_classify_fn(model: str = "claude-sonnet-4-20250514"):
    """Create an LLM classification function using the Anthropic API."""
    import os
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError(
            "anthropic package required for LLM normalization mode. "
            "Install with: pip install anthropic"
        )

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable required for LLM normalization mode"
        )

    client = Anthropic()

    def classify(prompt: str) -> str:
        logger.info("Calling %s for hierarchy classification...", model)
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        logger.debug("LLM response: %s", text[:200])
        return text

    return classify


def _output_root() -> Path:
    return settings.workspace_path / "output"


def _rel_path(abs_path: Path | str) -> str:
    """Convert an absolute path to relative-to-workspace for API responses."""
    try:
        return str(Path(abs_path).relative_to(settings.workspace_path))
    except ValueError:
        return str(abs_path)


def _validate_id(value: str, label: str = "ID") -> None:
    """Validate that an ID is safe for use as a filesystem path component."""
    if not _SAFE_ID_RE.match(value):
        raise ValueError(f"Invalid {label}: {value!r} (must be 1-64 alphanumeric/dash/underscore chars)")


def _state_path(project_id: str) -> Path:
    _validate_id(project_id, "project_id")
    return _output_root() / project_id / "state.json"


def _load_state(project_id: str) -> ProjectState:
    path = _state_path(project_id)
    if not path.exists():
        raise FileNotFoundError(f"Project not found: {project_id}")
    return ProjectState.model_validate_json(path.read_text())


def _save_state(state: ProjectState) -> None:
    path = _state_path(state.project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2))


def _update_stage(project_id: str, stage: str, status: StageStatus,
                  error: str | None = None) -> ProjectState:
    """Update a stage's status in the project state file."""
    state = _load_state(project_id)
    ss = state.stages[stage]
    ss.status = status
    if status == StageStatus.running:
        ss.started_at = datetime.now(timezone.utc)
        ss.completed_at = None
        ss.error = None
    elif status in (StageStatus.completed, StageStatus.failed):
        ss.completed_at = datetime.now(timezone.utc)
    if error:
        ss.error = error
    _save_state(state)
    return state


# -- Project CRUD -------------------------------------------------------------

def create_project(data_dir: str, project_name: str | None = None) -> ProjectState:
    """Create a new project with a state.json in the output directory."""
    # Resolve data_dir relative to workspace if not absolute
    data_path = Path(data_dir)
    if not data_path.is_absolute():
        data_path = settings.workspace_path / data_dir

    if not data_path.exists():
        raise FileNotFoundError(f"Data directory not found: {data_path}")

    project_id = project_name or data_path.name
    output_dir = _output_root() / project_id

    if _state_path(project_id).exists():
        raise FileExistsError(f"Project already exists: {project_id}")

    output_dir.mkdir(parents=True, exist_ok=True)

    state = ProjectState(
        project_id=project_id,
        data_dir=str(data_path),
        output_dir=str(output_dir),
        created_at=datetime.now(timezone.utc),
    )
    _save_state(state)
    logger.info("Created project %s (data=%s, output=%s)", project_id, data_path, output_dir)
    return state


def list_projects() -> list[ProjectState]:
    """Scan output directory for projects with state.json."""
    root = _output_root()
    if not root.exists():
        return []

    projects = []
    for child in sorted(root.iterdir()):
        state_file = child / "state.json"
        if child.is_dir() and state_file.exists():
            try:
                projects.append(ProjectState.model_validate_json(state_file.read_text()))
            except Exception as exc:
                logger.warning("Skipping invalid project %s: %s", child.name, exc)
    return projects


def get_project(project_id: str) -> ProjectState:
    return _load_state(project_id)


# -- Stage 1: Profile ---------------------------------------------------------

async def run_profile(project_id: str, recursive: bool = True) -> dict:
    """Run TDV profiler on the project's data directory."""
    _ensure_imports()
    state = _load_state(project_id)
    _update_stage(project_id, "profile", StageStatus.running)

    try:
        config = _PipelineConfig(
            data_lake_dir=state.data_dir,
            output_dir=state.output_dir,
        )
        pipeline = _PreparationPipeline(config)
        result = await asyncio.to_thread(pipeline.run_stage1_profile)
        _update_stage(project_id, "profile", StageStatus.completed)
        if "graph_path" in result:
            result["graph_path"] = _rel_path(result["graph_path"])
        return result
    except Exception as exc:
        _update_stage(project_id, "profile", StageStatus.failed, error=str(exc))
        raise


def get_profile(project_id: str) -> dict | None:
    """Load tdv_graph.json and return structured profile data."""
    graph_path = _output_root() / project_id / "tdv_graph.json"
    if not graph_path.exists():
        return None
    with open(graph_path) as f:
        data = json.load(f)
    profiles = data.get("profiles", {})
    return {
        "graph_path": _rel_path(graph_path),
        "datasets": len(profiles),
        "discriminators": sum(
            len(p.get("discriminators", [])) for p in profiles.values()
        ),
        "profiles": profiles,
    }


# -- Stage 2: Normalize -------------------------------------------------------

async def run_normalize(
    project_id: str,
    columns: list[str] | None = None,
    mode: str = "rules",
    rules: dict | None = None,
    rules_path: str | None = None,
    fuzzy_threshold: int = 80,
    hierarchy_levels: list[str] | None = None,
    context: str | None = None,
    skip_columns: list[str] | None = None,
) -> dict:
    """Run entity normalization on profiled data."""
    _ensure_imports()
    state = _load_state(project_id)

    # Precondition: profile must be completed
    if state.stages["profile"].status != StageStatus.completed:
        raise ValueError("Profile stage must be completed before normalization")

    _update_stage(project_id, "normalize", StageStatus.running)

    try:
        # Wire up LLM classify function when mode is "llm"
        llm_fn = None
        if mode == "llm":
            llm_fn = _make_llm_classify_fn()

        config = _PipelineConfig(
            data_lake_dir=state.data_dir,
            output_dir=state.output_dir,
            normalization_mode=mode,
            fuzzy_threshold=fuzzy_threshold,
            hierarchy_levels=hierarchy_levels or [
                "product", "brand", "subcategory", "category", "department",
            ],
            normalize_columns=columns or [],
            skip_columns=skip_columns or [],
            rules=rules or {},
            rules_path=rules_path,
            context=context or "retail product catalog",
            llm_classify_fn=llm_fn,
        )
        pipeline = _PreparationPipeline(config)
        result = await asyncio.to_thread(pipeline.run_stage2_normalize)
        _update_stage(project_id, "normalize", StageStatus.completed)
        return result
    except Exception as exc:
        _update_stage(project_id, "normalize", StageStatus.failed, error=str(exc))
        raise


def get_normalize(project_id: str) -> dict | None:
    """Load norm_graph_*.json files and return structured normalization data."""
    output_dir = _output_root() / project_id
    norm_files = list(output_dir.glob("norm_graph_*.json"))
    if not norm_files:
        return None

    columns = {}
    for f in norm_files:
        col_name = f.stem.replace("norm_graph_", "")
        with open(f) as fp:
            data = json.load(fp)
        columns[col_name] = {
            "norm_graph_path": _rel_path(f),
            "summary": data.get("summary", {}),
        }

    return {
        "columns_normalized": len(columns),
        "columns": columns,
    }


# -- Stage 3: Plan ------------------------------------------------------------

async def run_plan(
    project_id: str,
    dataset_ids: list[str] | None = None,
    target_value: str | None = None,
    target_discriminator: str | None = None,
    segment_by: list[str] | None = None,
) -> dict:
    """Build a data plan from profile + normalization results."""
    _ensure_imports()
    state = _load_state(project_id)

    # Precondition: profile must be completed
    if state.stages["profile"].status != StageStatus.completed:
        raise ValueError("Profile stage must be completed before plan building")

    _update_stage(project_id, "plan", StageStatus.running)

    try:
        config = _PipelineConfig(
            data_lake_dir=state.data_dir,
            output_dir=state.output_dir,
        )
        pipeline = _PreparationPipeline(config)

        if target_value:
            # Build plan via PlanBuilder directly for target_value mode
            from data_prep.graph_store import GraphStore
            from data_prep.plan_builder import PlanBuilder

            tdv_path = str(_output_root() / project_id / "tdv_graph.json")
            graph, profiles = GraphStore.load(tdv_path)

            # Load norm graphs
            norm_graphs = {}
            for ng_path in (_output_root() / project_id).glob("norm_graph_*.json"):
                col = ng_path.stem.replace("norm_graph_", "")
                norm_graphs[col] = GraphStore.load_norm(str(ng_path))

            builder = PlanBuilder(graph, profiles, norm_graphs=norm_graphs)
            plan = builder.build_plan_for_value(target_value, target_discriminator)
        else:
            plan = await asyncio.to_thread(
                pipeline.run_stage3_plan,
                dataset_ids=dataset_ids,
            )

        # Filter segmentation to selected discriminators only
        if segment_by:
            allowed_prefixes = tuple(f"norm_{col}_" for col in segment_by)
            plan.segment_by = [s for s in plan.segment_by if s.startswith(allowed_prefixes)]
            plan.normalization_sql = {k: v for k, v in plan.normalization_sql.items() if k in segment_by}
            plan.segment_estimates = {
                k: v for k, v in plan.segment_estimates.items()
                if any(k.startswith(col) for col in segment_by)
            }

        # Save plan
        plan_data = {
            "primary_dataset": plan.primary_dataset,
            "supplementary_datasets": plan.supplementary_datasets,
            "normalization_sql": plan.normalization_sql,
            "segment_by": plan.segment_by,
            "segment_estimates": plan.segment_estimates,
        }
        plan_path = _output_root() / project_id / "data_plan.json"
        with open(plan_path, "w") as f:
            json.dump(plan_data, f, indent=2, default=str)

        _update_stage(project_id, "plan", StageStatus.completed)

        # Return plan data
        return get_plan(project_id) or {}
    except Exception as exc:
        _update_stage(project_id, "plan", StageStatus.failed, error=str(exc))
        raise


def get_plan(project_id: str) -> dict | None:
    """Load data_plan.json."""
    plan_path = _output_root() / project_id / "data_plan.json"
    if not plan_path.exists():
        return None
    with open(plan_path) as f:
        return json.load(f)


# -- Stage 4: Manifest --------------------------------------------------------

async def run_manifest(
    project_id: str,
    timestamp_col: str | None = None,
    dataset_name: str | None = None,
    data_path: str | None = None,
    deviations: dict | None = None,
    segment_by: list[str] | None = None,
) -> dict:
    """Generate a batch_runner manifest from the data plan."""
    _ensure_imports()
    state = _load_state(project_id)

    # Precondition: plan must be completed
    if state.stages["plan"].status != StageStatus.completed:
        raise ValueError("Plan stage must be completed before manifest generation")

    _update_stage(project_id, "manifest", StageStatus.running)

    try:
        config = _PipelineConfig(
            data_lake_dir=state.data_dir,
            output_dir=state.output_dir,
            segment_by=segment_by or [],
        )
        pipeline = _PreparationPipeline(config)

        # Load the plan
        plan_data = get_plan(project_id)
        if not plan_data:
            raise ValueError("No data plan found")

        # Reconstruct DataPlan from saved JSON
        from data_prep.plan_builder import DataPlan
        plan = DataPlan(
            primary_dataset=plan_data.get("primary_dataset"),
            supplementary_datasets=plan_data.get("supplementary_datasets", []),
            normalization_sql=plan_data.get("normalization_sql", {}),
            segment_by=plan_data.get("segment_by", []),
            segment_estimates=plan_data.get("segment_estimates", {}),
        )
        pipeline._plan = plan

        manifest = pipeline.generate_manifest(
            plan=plan,
            timestamp_col=timestamp_col,
            dataset_name=dataset_name,
            data_path=data_path,
        )

        # Apply deviation overrides
        if deviations:
            manifest["deviations"] = {**manifest.get("deviations", {}), **deviations}

        # Save as YAML
        manifest_path = _output_root() / project_id / "manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.safe_dump(manifest, f, default_flow_style=False, sort_keys=False)

        _update_stage(project_id, "manifest", StageStatus.completed)
        return manifest
    except Exception as exc:
        _update_stage(project_id, "manifest", StageStatus.failed, error=str(exc))
        raise


def get_manifest(project_id: str) -> dict | None:
    """Load manifest.yaml."""
    manifest_path = _output_root() / project_id / "manifest.yaml"
    if not manifest_path.exists():
        return None
    with open(manifest_path) as f:
        return yaml.safe_load(f)


def edit_manifest(project_id: str, edits: dict) -> dict:
    """Merge edits into the existing manifest.yaml."""
    manifest = get_manifest(project_id)
    if manifest is None:
        raise FileNotFoundError("No manifest found for project")

    _deep_merge(manifest, edits)

    manifest_path = _output_root() / project_id / "manifest.yaml"
    with open(manifest_path, "w") as f:
        yaml.safe_dump(manifest, f, default_flow_style=False, sort_keys=False)

    return manifest


def _deep_merge(base: dict, overrides: dict) -> None:
    """Recursively merge overrides into base dict (in-place)."""
    for key, value in overrides.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


# -- Stage 5: Batch Run -------------------------------------------------------

async def run_batch_pipeline(
    project_id: str,
    max_workers: int = 4,
    run_name: str | None = None,
) -> dict:
    """Execute batch runner against the project manifest."""
    _ensure_imports()
    state = _load_state(project_id)

    # Precondition: manifest must be completed
    if state.stages["manifest"].status != StageStatus.completed:
        raise ValueError("Manifest stage must be completed before batch execution")

    _update_stage(project_id, "run", StageStatus.running)

    try:
        manifest_path = _output_root() / project_id / "manifest.yaml"
        manifest = _load_manifest(str(manifest_path))

        # Create run directory
        run_id = run_name or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        _validate_id(run_id, "run_id")
        run_dir = _output_root() / project_id / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        result = await asyncio.to_thread(
            _run_batch,
            manifest=manifest,
            run_dir=run_dir,
            max_workers=max_workers,
        )
        _update_stage(project_id, "run", StageStatus.completed)
        return {**result, "run_id": run_id}
    except Exception as exc:
        _update_stage(project_id, "run", StageStatus.failed, error=str(exc))
        raise


def list_runs(project_id: str) -> list[dict]:
    """List batch runs for a project."""
    runs_dir = _output_root() / project_id / "runs"
    if not runs_dir.exists():
        return []

    runs = []
    for child in sorted(runs_dir.iterdir()):
        if not child.is_dir():
            continue
        summary_path = child / "batch_summary.json"
        if summary_path.exists():
            with open(summary_path) as f:
                summary = json.load(f)
            runs.append({
                "run_id": child.name,
                "run_dir": str(child),
                **summary,
            })
        else:
            runs.append({
                "run_id": child.name,
                "run_dir": str(child),
                "status": "in_progress",
            })
    return runs


def get_run(project_id: str, run_id: str) -> dict | None:
    """Load batch run data. Returns summary if complete, stub if in-progress, None if missing."""
    _validate_id(run_id, "run_id")
    run_dir = _output_root() / project_id / "runs" / run_id
    if not run_dir.is_dir():
        return None
    summary_path = run_dir / "batch_summary.json"
    if summary_path.exists():
        with open(summary_path) as f:
            return {"run_id": run_id, "run_dir": _rel_path(run_dir), **json.load(f)}
    # Directory exists but no summary — run is in progress or crashed
    return {"run_id": run_id, "run_dir": _rel_path(run_dir), "status": "in_progress"}


# App root inside the container (where code + MCP servers live)
_APP_ROOT = Path("/opt/agent")


# -- Stage 6: Report Generation -----------------------------------------------

def _load_report_agent_prompt() -> str:
    """Load the report-agent system prompt, stripping YAML frontmatter."""
    # Try container path first, then project root
    candidates = [
        _APP_ROOT / ".claude" / "agents" / "report-agent.md",
        Path(__file__).resolve().parents[2] / ".claude" / "agents" / "report-agent.md",
    ]
    for path in candidates:
        if path.is_file():
            raw = path.read_text()
            # Strip YAML frontmatter (lines between --- markers)
            if raw.startswith("---"):
                end = raw.find("---", 3)
                if end != -1:
                    raw = raw[end + 3:].lstrip("\n")
            return raw

    raise FileNotFoundError(
        f"report-agent.md not found; searched {[str(p) for p in candidates]}"
    )


def _build_run_context(project_id: str, run_id: str) -> dict:
    """Load run directory, batch summary, and data notes for a completed run.

    Returns dict with keys: run_dir (Path), abs_run_dir (str),
    batch_summary (dict), data_notes (str | None).
    """
    _validate_id(project_id, "project_id")
    _validate_id(run_id, "run_id")

    run_dir = _output_root() / project_id / "runs" / run_id
    summary_path = run_dir / "batch_summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(
            f"Run not found or incomplete: {project_id}/runs/{run_id} "
            f"(missing batch_summary.json)"
        )

    with open(summary_path) as f:
        batch_summary = json.load(f)

    data_notes: str | None = None
    for notes_path in [
        _output_root() / project_id / "data-notes.md",
        _output_root() / "data-notes.md",
    ]:
        if notes_path.is_file():
            data_notes = notes_path.read_text()
            break

    return {
        "run_dir": run_dir,
        "abs_run_dir": str(run_dir.resolve()),
        "batch_summary": batch_summary,
        "data_notes": data_notes,
    }


async def generate_report(
    project_id: str,
    run_id: str,
    max_turns: int = 50,
    prompt: str | None = None,
) -> dict:
    """Generate an analysis report for a completed batch run using the Claude Agent SDK."""
    ctx = _build_run_context(project_id, run_id)
    abs_run_dir = ctx["abs_run_dir"]

    # Load report-agent system prompt
    report_system_prompt = _load_report_agent_prompt()

    # Build user prompt
    user_prompt = (
        f"Generate a report for the following batch run.\n\n"
        f"**Run directory**: {abs_run_dir}\n"
        f"**Data notes**: {ctx['data_notes'] or 'None available'}\n"
        f"**Batch summary**: {json.dumps(ctx['batch_summary'], indent=2)}\n\n"
        f"Scan the run directory, generate charts, and compose the analysis report.\n"
        f"Write the report to {abs_run_dir}/analysis_report.md and charts to {abs_run_dir}/charts/."
    )

    if prompt:
        user_prompt += f"\n\n**Additional instructions**: {prompt}"

    # Lazy import to avoid circular deps
    from app.services.claude_session import stream_chat

    logger.info("Starting report generation for %s/runs/%s", project_id, run_id)

    # Consume all SDK events
    async for event in stream_chat(
        user_message=user_prompt,
        system_prompt=report_system_prompt,
        max_turns=max_turns,
    ):
        event_type = event.get("type")
        if event_type == "error":
            raise RuntimeError(f"Report generation SDK error: {event.get('content')}")
        if event_type == "done":
            break

    # Verify output
    report_path = ctx["run_dir"] / "analysis_report.md"
    if not report_path.exists():
        raise RuntimeError(
            f"Report agent completed but analysis_report.md was not created in {abs_run_dir}"
        )

    return get_report(project_id, run_id)


async def chat_with_run(
    project_id: str,
    run_id: str,
    message: str,
    session_id: str | None = None,
    max_turns: int = 25,
) -> dict:
    """Answer ad-hoc questions about a completed batch run using the Claude Agent SDK."""
    ctx = _build_run_context(project_id, run_id)
    abs_run_dir = ctx["abs_run_dir"]
    batch_summary = ctx["batch_summary"]
    data_notes = ctx["data_notes"]

    # Build scenario artifact listing
    scenarios = batch_summary.get("scenarios", {})
    artifact_lines = []
    for scenario_name in scenarios:
        artifact_lines.append(
            f"- {scenario_name}/segments/*.parquet — per-segment time series\n"
            f"- {scenario_name}/baselines/{{segment}}/ — baseline decomposition "
            f"(manifest.json, decompositions/)\n"
            f"- {scenario_name}/results/{{segment}}.json — deviation detection results"
        )
    artifacts_block = "\n".join(artifact_lines) if artifact_lines else (
        "- segments/*.parquet — per-segment time series\n"
        "- baselines/{segment}/ — baseline decomposition\n"
        "- results/{segment}.json — deviation detection results"
    )

    system_prompt = (
        "You are a time-series signal analysis expert with access to a completed "
        "batch run's artifacts. Answer the user's questions using specific numbers "
        "from the data. You can read files and run Python scripts for analysis.\n\n"
        f"**Run directory**: {abs_run_dir}\n"
        f"**Data notes**: {data_notes or 'None available'}\n"
        f"**Batch summary**:\n```json\n{json.dumps(batch_summary, indent=2)}\n```\n\n"
        f"Available artifacts:\n{artifacts_block}\n\n"
        "When answering:\n"
        "- Cite specific numbers, dates, and segment names from the data\n"
        "- If the user asks for a chart, generate it as a PNG in the run's charts/ directory\n"
        "- Be concise but thorough"
    )

    from app.services.claude_session import stream_chat

    logger.info("Starting chat for %s/runs/%s (session=%s)", project_id, run_id, session_id)

    response_parts: list[str] = []
    result_session_id: str | None = session_id

    async for event in stream_chat(
        user_message=message,
        session_id=session_id,
        system_prompt=system_prompt,
        max_turns=max_turns,
    ):
        event_type = event.get("type")
        if event_type == "session":
            result_session_id = event.get("session_id", result_session_id)
        elif event_type == "text":
            response_parts.append(event.get("content", ""))
        elif event_type == "error":
            raise RuntimeError(f"Chat SDK error: {event.get('content')}")
        elif event_type == "done":
            break

    return {
        "session_id": result_session_id,
        "response": "".join(response_parts),
    }


def get_report(project_id: str, run_id: str) -> dict | None:
    """Load a generated report and its chart list."""
    _validate_id(project_id, "project_id")
    _validate_id(run_id, "run_id")

    run_dir = _output_root() / project_id / "runs" / run_id
    report_path = run_dir / "analysis_report.md"
    if not report_path.exists():
        return None

    charts_dir = run_dir / "charts"
    charts = sorted(
        _rel_path(p) for p in charts_dir.glob("*.png")
    ) if charts_dir.exists() else []

    stat = report_path.stat()
    return {
        "report_path": _rel_path(report_path),
        "charts": charts,
        "content": report_path.read_text(),
        "generated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
    }
