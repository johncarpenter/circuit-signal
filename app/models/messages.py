"""Chat WebSocket message schemas."""

from enum import Enum

from pydantic import BaseModel, Field


class ChatInput(BaseModel):
    """Client -> Server message."""

    message: str = Field(..., description="User message text")
    context: dict = Field(default_factory=dict, description="Optional context (e.g. session_id)")


class MessageType(str, Enum):
    text = "text"
    tool_use = "tool_use"
    tool_result = "tool_result"
    error = "error"
    done = "done"


class ChatOutput(BaseModel):
    """Server -> Client message frame."""

    type: MessageType
    content: str | None = None
    tool: str | None = None
    input: dict | None = None
    output: str | None = None
