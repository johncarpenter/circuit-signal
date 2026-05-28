"""FastAPI application for the Circuit Signal Agent container."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.services.task_manager import (
    in_flight_tasks,
    is_shutting_down,
    register_task,
    set_shutting_down,
)

# Configure structured JSON logging
_log_handler = logging.StreamHandler(sys.stdout)
_log_handler.setFormatter(
    logging.Formatter(
        '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}'
    )
)
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    handlers=[_log_handler],
)
logger = logging.getLogger("agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info(f"Agent '{settings.agent_name}' starting up")
    logger.info(f"Workspace: {settings.workspace_path}")
    if not settings.claude_code_oauth_token:
        logger.warning("CLAUDE_CODE_OAUTH_TOKEN not set — Claude SDK calls will fail")

    yield

    # Shutdown
    set_shutting_down()
    logger.info("Shutting down — waiting for in-flight tasks")

    _in_flight = in_flight_tasks()
    if _in_flight:
        logger.info(f"Waiting for {len(_in_flight)} in-flight task(s)")
        done, pending = await asyncio.wait(_in_flight, timeout=30)
        if pending:
            logger.warning(f"Cancelling {len(pending)} task(s) after timeout")
            for task in pending:
                task.cancel()

    logger.info("Shutdown complete")


app = FastAPI(
    title="Circuit Signal Agent",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow frontend connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers — conditional imports allow partial deploys
from app.routers.status import router as status_router  # noqa: E402
app.include_router(status_router, tags=["status"])

try:
    from app.routers.workspace import router as workspace_router
    app.include_router(workspace_router, tags=["workspace"])
except ImportError:
    pass

try:
    from app.routers.chat import router as chat_router
    app.include_router(chat_router, tags=["chat"])
except ImportError:
    pass

try:
    from app.routers.pipeline import router as pipeline_router
    app.include_router(pipeline_router, tags=["pipeline"])
except ImportError:
    pass
