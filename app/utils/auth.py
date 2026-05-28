"""Bearer token authentication for HTTP and WebSocket endpoints."""

from fastapi import Depends, HTTPException, Query, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_http_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Verify bearer token on HTTP requests."""
    if not settings.agent_api_token:
        # No token configured — allow all requests (dev mode)
        return ""

    if credentials is None or credentials.credentials != settings.agent_api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


async def verify_ws_token(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> str:
    """Verify token on WebSocket connections via query parameter."""
    if not settings.agent_api_token:
        return ""

    if token != settings.agent_api_token:
        raise WebSocketException(code=4401, reason="Unauthorized")
    return token
