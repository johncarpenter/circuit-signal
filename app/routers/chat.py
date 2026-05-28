"""WebSocket /ws/chat — Interactive Claude chat session."""

import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.models.messages import ChatInput
from app.services.claude_session import stream_chat
from app.utils.auth import verify_ws_token

logger = logging.getLogger("agent.chat")

router = APIRouter()


@router.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
    _: str = Depends(verify_ws_token),
):
    """Interactive chat session with Claude Agent SDK.

    Client sends: {"message": "...", "context": {...}}
    Server streams: {"type": "session|text|tool_use|tool_result|error|done", ...}

    The server sends a {"type": "session", "session_id": "..."} event on
    each interaction. The client stores the session_id and sends it back
    via context.session_id on subsequent messages for multi-turn resume.
    """
    await websocket.accept()
    logger.info("Chat WebSocket connected")

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                data = ChatInput.model_validate_json(raw)
            except Exception as e:
                await websocket.send_json({"type": "error", "content": f"Invalid message: {e}"})
                continue

            session_id = data.context.get("session_id")
            system_prompt = data.context.get("system_prompt")
            allowed_tools = data.context.get("allowed_tools")
            max_turns = data.context.get("max_turns", 25)

            async for event in stream_chat(
                user_message=data.message,
                session_id=session_id,
                system_prompt=system_prompt,
                allowed_tools=allowed_tools,
                max_turns=max_turns,
            ):
                if event.get("type") == "session":
                    logger.info(f"Session ID: {event['session_id']}")

                await websocket.send_json(event)

    except WebSocketDisconnect:
        logger.info("Chat WebSocket disconnected")
    except Exception:
        logger.exception("Chat WebSocket error")
