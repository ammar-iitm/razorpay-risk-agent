"""
day1/calculator_tool.py — Agent SDK Exercise 1: a working custom tool.

Straight from the Agent SDK docs' quickstart pattern
(https://code.claude.com/docs/en/agent-sdk/python), adapted to actually run.
This is deliberately trivial (add/multiply) — the point of Day 1 isn't the
math, it's proving your environment is wired correctly before you touch
anything Razorpay-shaped tomorrow.

Requires: an authenticated `claude` CLI on PATH (claude_agent_sdk drives it
as a subprocess) OR ANTHROPIC_API_KEY set in the environment. See the bottom
of this file for both options.

Run:  python3 day1/calculator_tool.py
"""

import asyncio
from typing import Any

from claude_agent_sdk import (
    tool,
    create_sdk_mcp_server,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    AssistantMessage,
    TextBlock,
)


@tool(
    name="calculate",
    description="Perform basic arithmetic: add or multiply two numbers.",
    input_schema={"operation": str, "a": float, "b": float},
)
async def calculate(args: dict[str, Any]) -> dict[str, Any]:
    operation = args["operation"]
    a, b = args["a"], args["b"]

    if operation == "add":
        result = a + b
    elif operation == "multiply":
        result = a * b
    else:
        result = f"Unknown operation: {operation}"

    return {"content": [{"type": "text", "text": f"Result: {result}"}]}


calculator_server = create_sdk_mcp_server(
    name="calculator",
    version="1.0.0",
    tools=[calculate],
)

options = ClaudeAgentOptions(
    system_prompt="You are a helpful math assistant. Use the calculate tool for arithmetic.",
    mcp_servers={"calc": calculator_server},
    allowed_tools=["mcp__calc__calculate"],
    permission_mode="acceptEdits",
    max_turns=4,
)


async def main() -> None:
    async with ClaudeSDKClient(options=options) as client:
        await client.query("What is 5 plus 3? Then multiply that result by 2.")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Claude: {block.text}")


if __name__ == "__main__":
    # Option A (recommended): make sure `claude` on PATH is logged in
    #   claude setup-token   (or however you authenticated Claude Code locally)
    # Option B: export ANTHROPIC_API_KEY=sk-ant-...   (pay-per-token, from
    #   console.anthropic.com — separate from any Claude.ai subscription)
    asyncio.run(main())