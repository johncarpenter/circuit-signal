"""Workspace file browser and upload endpoints."""

import base64
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.config import settings
from app.utils.auth import verify_http_token

router = APIRouter()


def _safe_path(path: str) -> Path:
    """Resolve path within workspace, preventing traversal."""
    workspace = settings.workspace_path.resolve()
    resolved = (workspace / path).resolve()
    if not resolved.is_relative_to(workspace):
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    return resolved


def _list_directory(dir_path: Path) -> list[dict]:
    """List entries in a directory."""
    entries = []
    for child in sorted(dir_path.iterdir()):
        if child.name.startswith("."):
            continue
        entry = {
            "name": child.name,
            "type": "directory" if child.is_dir() else "file",
        }
        if child.is_file():
            entry["size_bytes"] = child.stat().st_size
        entries.append(entry)
    return entries


@router.get("/workspace/{path:path}")
async def get_workspace_path(
    path: str = "",
    _: str = Depends(verify_http_token),
) -> dict:
    """Browse workspace files. Returns directory listing or file content."""
    resolved = _safe_path(path)

    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {path}")

    if resolved.is_dir():
        return {
            "path": path,
            "type": "directory",
            "entries": _list_directory(resolved),
        }

    # Return file metadata + content for text files under 10MB
    size_bytes = resolved.stat().st_size
    max_content_size = 10 * 1024 * 1024  # 10MB

    result = {
        "path": path,
        "type": "file",
        "name": resolved.name,
        "size_bytes": size_bytes,
        "suffix": resolved.suffix,
    }

    text_suffixes = {
        ".txt", ".csv", ".tsv", ".json", ".yaml", ".yml",
        ".xml", ".md", ".log", ".py", ".sql", ".sh", ".toml",
        ".cfg", ".ini", ".html", ".css", ".js", ".ts",
    }

    if resolved.suffix.lower() in text_suffixes and size_bytes <= max_content_size:
        try:
            result["content"] = resolved.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            pass  # Skip content for binary/unreadable files

    # Serve images as base64 data URIs (for chart viewing, capped at 5MB)
    image_suffixes = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
    max_image_size = 5 * 1024 * 1024  # 5MB
    if resolved.suffix.lower() in image_suffixes and size_bytes <= max_image_size:
        mime_types = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
        }
        mime = mime_types.get(resolved.suffix.lower(), "application/octet-stream")
        raw = resolved.read_bytes()
        result["content_base64"] = base64.b64encode(raw).decode("ascii")
        result["mime_type"] = mime

    return result


@router.get("/workspace/")
@router.get("/workspace")
async def get_workspace_root(_: str = Depends(verify_http_token)) -> dict:
    """List workspace root directory."""
    workspace = settings.workspace_path
    if not workspace.exists():
        return {"path": "", "type": "directory", "entries": []}
    return {
        "path": "",
        "type": "directory",
        "entries": _list_directory(workspace),
    }


@router.post("/workspace/{path:path}")
async def upload_to_workspace(
    path: str,
    file: UploadFile,
    _: str = Depends(verify_http_token),
) -> dict:
    """Upload a file to the workspace."""
    resolved = _safe_path(path)

    # Ensure parent directory exists
    resolved.parent.mkdir(parents=True, exist_ok=True)

    with open(resolved, "wb") as f:
        shutil.copyfileobj(file.file, f)

    return {
        "path": path,
        "name": resolved.name,
        "size_bytes": resolved.stat().st_size,
        "status": "uploaded",
    }
