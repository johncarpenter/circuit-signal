"""Claude Agent SDK wrapper for WebSocket chat sessions."""

import copy
import json
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("agent.claude")

# Import SDK — claude-agent-sdk (>=0.1.0)
try:
    from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, query as _query
    _SDK_OK = True
except ImportError:
    _SDK_OK = False

_BASE_SYSTEM_PROMPT = (
    "You are a time-series signal analysis agent. You have access to the workspace "
    "at /workspace containing datasets in data/, analysis outputs in output/, and "
    "reports in reports/.\n\n"
    "You operate a 3-layer analysis pipeline:\n"
    "- Layer 0 (data-loader): Load, clean, segment, and export datasets\n"
    "- Layer 1 (signal-discovery): Baseline decomposition, deviation detection, forecasting\n"
    "- Layer 2 (signal-correlation): Cross-segment correlation and insight discovery\n\n"
    "The query-planner helps you discover datasets and resolve join paths using "
    "TDV (Time-Discriminator-Value) graphs.\n\n"
    "Follow the standard workflow: inspect → clean → segment → baseline → "
    "deviations → correlate → report."
)

# App root inside the container (where code + MCP servers live)
_APP_ROOT = Path("/opt/agent")

# Local dev path prefix to detect and remap
_LOCAL_PREFIX = "/Users/"


def _fix_path(p: str) -> str:
    """Normalise a path from .mcp.json for the container environment."""
    # Relative path like "mcp/layer0" → absolute container path
    if "/" in p and not p.startswith(("/", "-")):
        return str(_APP_ROOT / p)
    # Absolute local-dev path → remap to container
    if p.startswith(_LOCAL_PREFIX):
        for marker in ("mcp/layer0", "mcp/layer1", "mcp/layer2", "mcp/query-planner"):
            idx = p.find(marker)
            if idx >= 0:
                return str(_APP_ROOT / p[idx:])
        idx = p.find("workspace/")
        if idx >= 0:
            return "/" + p[idx:]
    return p


def _build_agents() -> dict[str, "AgentDefinition"] | None:
    """Build programmatic subagent definitions for task delegation."""
    if not _SDK_OK:
        return None

    return {
        "segment-worker": AgentDefinition(
            description=(
                "Execute a per-segment analysis task. Use when you need to run "
                "Layer 1 analysis (baseline, deviations, forecast) on individual "
                "segments in parallel."
            ),
            prompt=(
                "You are a signal analysis subagent. You have access to the workspace "
                "at /workspace. Execute the segment analysis task described in your "
                "prompt using the signal-discovery MCP tools. Return a clear summary "
                "of findings including any anomalies or deviations detected."
            ),
            tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        ),
    }


def _build_mcp_servers() -> dict[str, dict] | None:
    """Load MCP server config from .mcp.json, fixing paths for container."""
    config_path = _APP_ROOT / ".mcp.json"
    if not config_path.is_file():
        return None

    try:
        with open(config_path) as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read .mcp.json")
        return None

    servers = copy.deepcopy(raw.get("mcpServers", {}))
    if not servers:
        return None

    for name, srv in servers.items():
        if "command" in srv:
            srv["command"] = _fix_path(srv["command"])
        if "args" in srv:
            srv["args"] = [_fix_path(a) for a in srv["args"]]
        if "cwd" in srv:
            srv["cwd"] = _fix_path(srv["cwd"])
        if "env" in srv:
            for k, v in list(srv["env"].items()):
                if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                    var_name = v[2:-1]
                    resolved = os.environ.get(var_name)
                    if resolved is None:
                        logger.warning(f"MCP env var ${{{var_name}}} not set for server '{name}'")
                        resolved = ""
                    srv["env"][k] = resolved
                elif isinstance(v, str):
                    srv["env"][k] = _fix_path(v)
        logger.debug(f"MCP server configured: {name}")

    return servers


async def stream_chat(
    user_message: str,
    session_id: str | None = None,
    system_prompt: str | None = None,
    allowed_tools: list[str] | None = None,
    max_turns: int = 25,
) -> AsyncIterator[dict[str, Any]]:
    """Stream a chat interaction with Claude Agent SDK.

    Yields event dicts. The first event always includes a session_id
    that the caller should store for multi-turn resume.
    """
    if not _SDK_OK:
        yield {"type": "error", "content": "claude-agent-sdk not installed"}
        yield {"type": "done"}
        return

    if not settings.claude_code_oauth_token:
        yield {"type": "error", "content": "CLAUDE_CODE_OAUTH_TOKEN not set"}
        yield {"type": "done"}
        return

    agents = _build_agents()
    mcp_servers = _build_mcp_servers() or {}

    logger.info(
        f"SDK config: mcp_servers={list(mcp_servers.keys())}, "
        f"agents={len(agents or {})}, "
        f"allowed_tools={'all' if allowed_tools is None else allowed_tools}"
    )

    def _on_stderr(line: str) -> None:
        logger.warning("SDK stderr: %s", line.rstrip())

    opts_kwargs: dict[str, Any] = {
        "max_turns": max_turns,
        "system_prompt": system_prompt or _BASE_SYSTEM_PROMPT,
        "permission_mode": "bypassPermissions",
        "max_buffer_size": 10 * 1024 * 1024,  # 10MB
        "cwd": str(settings.workspace_path),
        "setting_sources": ["project"],
        "agents": agents,
        "mcp_servers": mcp_servers,
        "stderr": _on_stderr,
    }
    if allowed_tools is not None:
        opts_kwargs["allowed_tools"] = allowed_tools

    options = ClaudeAgentOptions(**opts_kwargs)

    if session_id:
        options.resume = session_id
        logger.info(f"Resuming session {session_id}")

    logger.info(f"Starting SDK query (resume={session_id is not None})")

    try:
        event_count = 0
        async for event in _query(prompt=user_message, options=options):
            event_count += 1
            cls = type(event).__name__
            logger.debug(f"SDK event #{event_count}: {cls}")

            if cls == "SystemMessage":
                if getattr(event, "subtype", None) == "init":
                    sid = getattr(event, "session_id", None)
                    if sid:
                        yield {"type": "session", "session_id": sid}

            elif cls == "AssistantMessage":
                for block in event.content:
                    block_type = type(block).__name__
                    if block_type == "TextBlock":
                        yield {"type": "text", "content": block.text}
                    elif block_type == "ToolUseBlock":
                        yield {
                            "type": "tool_use",
                            "tool": getattr(block, "name", "unknown"),
                            "input": getattr(block, "input", {}),
                        }
                    elif block_type == "ToolResultBlock":
                        yield {
                            "type": "tool_result",
                            "output": str(getattr(block, "content", "")),
                        }

            elif cls == "ResultMessage":
                logger.info(
                    f"SDK complete: subtype={event.subtype} "
                    f"turns={getattr(event, 'num_turns', '?')} "
                    f"cost=${getattr(event, 'total_cost_usd', 0):.4f}"
                )

        logger.info(f"SDK query finished ({event_count} events)")
        yield {"type": "done"}

    except Exception as e:
        logger.exception("Claude SDK error")
        yield {"type": "error", "content": str(e)}
        yield {"type": "done"}
