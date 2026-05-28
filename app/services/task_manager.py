"""Shared in-flight task tracking for graceful shutdown.

Both app.main (lifespan) and app.routers.pipeline (task submission)
import from here, avoiding a circular dependency.
"""

from __future__ import annotations

import asyncio

_in_flight: set[asyncio.Task] = set()
_shutting_down = False


def register_task(task: asyncio.Task) -> None:
    """Register an asyncio.Task for graceful shutdown tracking."""
    _in_flight.add(task)
    task.add_done_callback(_in_flight.discard)


def in_flight_tasks() -> set[asyncio.Task]:
    return _in_flight


def is_shutting_down() -> bool:
    return _shutting_down


def set_shutting_down() -> None:
    global _shutting_down
    _shutting_down = True
