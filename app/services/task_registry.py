"""In-memory async task registry for long-running pipeline operations."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("agent.task-registry")


class TaskInfo:
    """Tracks the state of an async task."""

    __slots__ = (
        "task_id", "status", "stage", "project_id",
        "started_at", "completed_at", "progress", "result", "error",
        "_asyncio_task",
    )

    def __init__(
        self,
        task_id: str,
        stage: str,
        project_id: str,
    ):
        self.task_id = task_id
        self.stage = stage
        self.project_id = project_id
        self.status = "running"
        self.started_at = datetime.now(timezone.utc)
        self.completed_at: Optional[datetime] = None
        self.progress: Optional[str] = None
        self.result: Any = None
        self.error: Optional[str] = None
        self._asyncio_task: Optional[asyncio.Task] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "stage": self.stage,
            "project_id": self.project_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
        }


class TaskRegistry:
    """Singleton registry for background pipeline tasks."""

    _instance: Optional[TaskRegistry] = None

    def __init__(self):
        self._tasks: dict[str, TaskInfo] = {}

    @classmethod
    def get(cls) -> TaskRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def submit(
        self,
        coro: Coroutine,
        stage: str,
        project_id: str,
        register_fn: Callable[[asyncio.Task], None] | None = None,
    ) -> TaskInfo:
        """Wrap a coroutine in an asyncio.Task and track it.

        Args:
            coro: The coroutine to execute.
            stage: Pipeline stage name (e.g. "normalize", "run").
            project_id: Associated project ID.
            register_fn: Optional callback to register the task for graceful
                shutdown (e.g. app.main.register_task).
        """
        task_id = uuid.uuid4().hex[:12]
        info = TaskInfo(task_id=task_id, stage=stage, project_id=project_id)

        async def _wrapper():
            try:
                info.result = await coro
                info.status = "completed"
            except Exception as exc:
                info.status = "failed"
                info.error = str(exc)
                logger.exception("Task %s failed: %s", task_id, exc)
            finally:
                info.completed_at = datetime.now(timezone.utc)

        asyncio_task = asyncio.create_task(_wrapper(), name=f"pipeline-{stage}-{task_id}")
        info._asyncio_task = asyncio_task
        self._tasks[task_id] = info

        if register_fn:
            register_fn(asyncio_task)

        logger.info("Submitted task %s (stage=%s, project=%s)", task_id, stage, project_id)
        return info

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        return self._tasks.get(task_id)
