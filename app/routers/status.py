"""GET /status — Agent status and health check."""

import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends

from app.config import settings
from app.utils.auth import verify_http_token

router = APIRouter()

_start_time = time.time()


def _count_datasets(data_dir: Path) -> list[dict]:
    """List dataset files in the data directory."""
    if not data_dir.exists():
        return []
    datasets = []
    for f in sorted(data_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in (".csv", ".parquet", ".json"):
            datasets.append({
                "name": f.name,
                "size_bytes": f.stat().st_size,
            })
    return datasets


@router.get("/status")
async def get_status(_: str = Depends(verify_http_token)) -> dict:
    """Return agent status, uptime, and workspace stats."""
    workspace = settings.workspace_path

    # Count files by top-level workspace directory
    dir_counts: dict[str, int] = {}
    if workspace.exists():
        for child in workspace.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                count = sum(1 for _ in child.rglob("*") if _.is_file())
                dir_counts[child.name] = count

    uptime_seconds = time.time() - _start_time

    # Auth status (never expose the token itself)
    auth_ok = bool(settings.claude_code_oauth_token)

    # Dataset inventory
    datasets = _count_datasets(workspace / "data")

    return {
        "agent_name": settings.agent_name,
        "status": "running",
        "uptime_seconds": round(uptime_seconds, 1),
        "started_at": datetime.fromtimestamp(_start_time, tz=timezone.utc).isoformat(),
        "workspace_path": str(workspace),
        "workspace_stats": dir_counts,
        "datasets": datasets,
        "auth_status": "authenticated" if auth_ok else "no_token",
    }
