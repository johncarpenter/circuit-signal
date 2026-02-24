"""Chainlit entry point for the Signal Discovery app."""

import os
import logging
from pathlib import Path

import chainlit as cl
from anthropic import Anthropic

from data_loader.storage import get_backend
from signal_correlation.store import SignalStore
from system_prompt import SYSTEM_PROMPT

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("signal-app")

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
WORK_DIR = Path(os.environ.get("SIGNAL_WORK_DIR", ".")).resolve()


@cl.on_chat_start
async def on_chat_start():
    """Initialize session state: Anthropic client, backends, message history."""
    # Anthropic client
    client = Anthropic()
    cl.user_session.set("client", client)

    # Layer 0: DuckDB backend (singleton — uses data_loader's global)
    data_dir = str(WORK_DIR / ".signal-data")
    get_backend(data_dir)
    logger.info("Layer 0 backend initialized at %s", data_dir)

    # Layer 2: SignalStore (per-session)
    store_path = str(WORK_DIR / ".signal-store" / "signals.duckdb")
    store = SignalStore(db_path=store_path)
    cl.user_session.set("store", store)
    logger.info("Layer 2 store initialized at %s", store_path)

    # Message history
    cl.user_session.set("messages", [])

    logger.info("Session started — model=%s, work_dir=%s", MODEL, WORK_DIR)


@cl.on_message
async def on_message(message: cl.Message):
    """Handle incoming user messages."""
    from agent import run_agent_loop

    messages = cl.user_session.get("messages")
    client = cl.user_session.get("client")
    store = cl.user_session.get("store")

    # Handle file uploads
    user_content = message.content
    if message.elements:
        upload_dir = WORK_DIR / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_paths = []
        for el in message.elements:
            if hasattr(el, "path") and el.path:
                dest = upload_dir / Path(el.path).name
                if not dest.exists():
                    import shutil
                    shutil.copy2(el.path, dest)
                file_paths.append(str(dest))
        if file_paths:
            paths_str = ", ".join(file_paths)
            user_content += f"\n\n[Uploaded files: {paths_str}]"

    messages.append({"role": "user", "content": user_content})

    await run_agent_loop(
        client=client,
        messages=messages,
        store=store,
        work_dir=str(WORK_DIR),
    )
