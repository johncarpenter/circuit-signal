"""WebSocket progress relay — subscribes to Redis pub/sub and relays to clients."""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import redis.asyncio as aioredis

from circuit_api.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/api/ws/runs/{run_id}")
async def run_progress(websocket: WebSocket, run_id: str):
    """WebSocket endpoint for real-time pipeline progress.

    Subscribes to Redis channel `progress:{run_id}` and relays events
    to the connected client. Closes when the run completes or errors.
    """
    await websocket.accept()

    redis = aioredis.from_url(settings.REDIS_URL)
    pubsub = redis.pubsub()
    channel = f"progress:{run_id}"

    try:
        await pubsub.subscribe(channel)
        logger.info("WebSocket client subscribed to %s", channel)

        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")

                await websocket.send_text(data)

                # Close on terminal states
                try:
                    event = json.loads(data)
                    if event.get("stage") in ("completed", "error"):
                        await websocket.close()
                        break
                except json.JSONDecodeError:
                    pass

            # Small yield to prevent busy-waiting
            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from %s", channel)
    except Exception as e:
        logger.error("WebSocket error for %s: %s", channel, e)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await redis.close()
