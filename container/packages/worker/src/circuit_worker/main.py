import logging

import os

from arq.connections import RedisSettings

from circuit_worker.tasks.profile import run_profile
from circuit_worker.tasks.analyze import run_analysis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WorkerSettings:
    """ARQ worker settings."""

    functions = [run_profile, run_analysis]
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379"))
    max_jobs = 1
    job_timeout = 1800  # 30 minutes

    @staticmethod
    async def on_startup(ctx):
        from circuit_worker.storage import storage
        storage.ensure_bucket()
        logger.info("Worker started — MinIO bucket ensured")

    @staticmethod
    async def on_shutdown(ctx):
        logger.info("Worker shutting down")
