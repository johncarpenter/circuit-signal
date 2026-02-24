"""Agentic loop — Claude API with tool calling via Chainlit UI."""

import json
import logging
import os

import chainlit as cl

from tools_schema import TOOLS
from tools_dispatch import dispatch_tool
from system_prompt import SYSTEM_PROMPT

logger = logging.getLogger("signal-app.agent")

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
MAX_ITERATIONS = 25


async def run_agent_loop(
    client,
    messages: list[dict],
    store,
    work_dir: str,
):
    """Run the agentic tool-calling loop until end_turn or max iterations."""

    for iteration in range(MAX_ITERATIONS):
        logger.info("Agent iteration %d", iteration + 1)

        response = await cl.make_async(client.messages.create)(
            model=MODEL,
            max_tokens=16384,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Collect the full assistant content for message history
        assistant_content = response.content

        # Process content blocks
        text_parts = []
        tool_uses = []

        for block in assistant_content:
            if block.type == "text" and block.text:
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        # Send any text as a chat message
        if text_parts:
            msg = cl.Message(content="\n\n".join(text_parts))
            await msg.send()

        # Append assistant message to history
        messages.append({
            "role": "assistant",
            "content": [_block_to_dict(b) for b in assistant_content],
        })

        # If no tool calls, we're done
        if response.stop_reason == "end_turn" or not tool_uses:
            break

        # Execute tool calls and collect results
        tool_results = []
        for tool_use in tool_uses:
            tool_name = tool_use.name
            tool_input = tool_use.input

            # Show tool execution as a Step
            async with cl.Step(name=tool_name, type="tool") as step:
                step.input = json.dumps(tool_input, indent=2, default=str)

                result_str = await dispatch_tool(
                    name=tool_name,
                    params=tool_input,
                    store=store,
                    work_dir=work_dir,
                )

                # Truncate display if very long
                display_result = result_str
                if len(display_result) > 5000:
                    display_result = display_result[:5000] + "\n... (truncated)"
                step.output = display_result

                # Generate charts if applicable
                try:
                    from tools_viz import maybe_create_charts
                    charts = maybe_create_charts(tool_name, result_str)
                    for chart_el in charts:
                        await chart_el.send()
                except Exception:
                    pass  # Viz is optional

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result_str,
            })

        # Append tool results to history
        messages.append({"role": "user", "content": tool_results})

    else:
        # Hit max iterations
        await cl.Message(
            content="Reached maximum iterations. Please continue the conversation to proceed."
        ).send()


def _block_to_dict(block) -> dict:
    """Convert an Anthropic content block to a serializable dict."""
    if block.type == "text":
        return {"type": "text", "text": block.text}
    elif block.type == "tool_use":
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    # Fallback
    return {"type": block.type}
