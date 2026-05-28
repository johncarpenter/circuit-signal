"""Redis pub/sub progress publisher."""
import json
import logging

logger = logging.getLogger(__name__)


class ProgressPublisher:
    """Publishes pipeline progress events to Redis pub/sub."""

    def __init__(self, redis_client):
        self.redis = redis_client

    async def publish(self, run_id: str, stage: str, segment: str | None = None, percent: float = 0.0):
        event = {
            "run_id": run_id,
            "stage": stage,
            "segment": segment,
            "percent": percent,
        }
        await self.redis.publish(f"progress:{run_id}", json.dumps(event))
        logger.debug(f"Progress: {event}")
