from arq import create_pool
from arq.connections import RedisSettings

from circuit_api.config import settings


async def get_arq_pool():
    return await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))


async def enqueue_profile(dataset_id: str):
    pool = await get_arq_pool()
    await pool.enqueue_job("run_profile", dataset_id)


async def enqueue_analysis(run_id: str):
    pool = await get_arq_pool()
    await pool.enqueue_job("run_analysis", run_id)
