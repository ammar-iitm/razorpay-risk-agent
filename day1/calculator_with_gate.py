"""
day1/calculator_with_gate.py — Agent SDK Exercise 2: prove the gate blocks.

Adds a "divide" operation and a can_use_tool permission handler that denies
divide-by-zero BEFORE the tool ever runs. This is the exact mechanism
policy_config / evaluate_policy() in agent/agent_tools.py plugs into for the
real project — hold_payment, submit_dispute_evidence, and accept_dispute are
all gated the same way, just with risk-score/amount conditions instead of
"is b zero".

Two ways to verify the block, both included:
  1. verify_handler_offline() — calls the permission handler directly with
     fake arguments. Zero API calls, zero cost, proves the LOGIC is correct.
  2. main() — the full live agent loop, asks Claude to divide by zero, and
     you watch it get denied in real time. Proves the WIRING is correct too.

Run:  python3 day1/calculator_with_gate.py            (offline check only)
      python3 day1/calculator_with_gate.py --live      (offline check + live run)
"""

import asyncio
import sys
from typing import Any

from claude_agent_sdk import (
    tool,
    create_sdk_mcp_server,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    AssistantMessage,
    TextBlock,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)


@tool(
    name="calculate",
    description="Perform basic arithmetic: add, multiply, or divide two numbers.",
    input_schema={"operation": str, "a": float, "b": float},
)
async def calculate(args: dict[str, Any]) -> dict[str, Any]:
    operation = args["operation"]
    a, b = args["a"], args["b"]

    if operation == "add":
        result = a + b
    elif operation == "multiply":
        result = a * b
    elif operation == "divide":
        result = a / b  # can_use_tool below guarantees b != 0 by the time we get here
    else:
        result = f"Unknown operation: {operation}"

    return {"content": [{"type": "text", "text": f"Result: {result}"}]}


async def custom_permission_handler(
    tool_name: str,
    input_data: dict[str, Any],
    context: ToolPermissionContext,
) -> PermissionResultAllow | PermissionResultDeny:
    """Block division by zero before the tool body ever executes.

    This is the SAME shape as evaluate_policy() in agent_tools.py: look at
    the tool call's arguments, check them against a rule, allow or deny.
    Nothing here depends on Claude's own judgment — the block is enforced
    in code the model cannot talk its way around.
    """
    if tool_name == "mcp__calc__calculate":
        if input_data.get("operation") == "divide" and input_data.get("b") == 0:
            return PermissionResultDeny(
                message="Cannot divide by zero.",
                interrupt=False,
            )
    return PermissionResultAllow(updated_input=input_data)


def verify_handler_offline() -> None:
    """Zero-cost, zero-API-call check that the gating LOGIC is correct."""

    class _FakeContext:
        pass

    async def _run() -> None:
        deny_case = await custom_permission_handler(
            "mcp__calc__calculate", {"operation": "divide", "a": 10, "b": 0}, _FakeContext()
        )
        allow_case = await custom_permission_handler(
            "mcp__calc__calculate", {"operation": "divide", "a": 10, "b": 2}, _FakeContext()
        )
        print("--- Offline permission-handler check (no API calls) ---")
        print("divide by 0  ->", type(deny_case).__name__, "|", getattr(deny_case, "message", ""))
        print("divide by 2  ->", type(allow_case).__name__)
        assert isinstance(deny_case, PermissionResultDeny), "divide-by-zero should have been DENIED"
        assert isinstance(allow_case, PermissionResultAllow), "divide-by-2 should have been ALLOWED"
        print("PASS: handler denies exactly the case it should, and only that case.")

    asyncio.run(_run())


calculator_server = create_sdk_mcp_server(
    name="calculator",
    version="1.0.0",
    tools=[calculate],
)

options = ClaudeAgentOptions(
    system_prompt=(
        "You are a helpful math assistant. Use the calculate tool for arithmetic. "
        "If a tool call is denied, report that plainly to the user instead of "
        "pretending it succeeded."
    ),
    mcp_servers={"calc": calculator_server},
    # NOTE: deliberately NOT in allowed_tools — an allowed_tools entry for a
    # whole tool auto-approves it before can_use_tool is ever consulted
    # (CanUseToolShadowedWarning), which would make this gate a no-op in the
    # live path. Leaving it out forces every call through custom_permission_handler.
    can_use_tool=custom_permission_handler,
    permission_mode="default",
    max_turns=4,
)


async def main() -> None:
    async with ClaudeSDKClient(options=options) as client:
        await client.query("What is 10 divided by 0? Then, separately, what is 10 divided by 2?")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Claude: {block.text}")


if __name__ == "__main__":
    verify_handler_offline()
    if "--live" in sys.argv:
        print("\n--- Live agent loop (real API call) ---")
        asyncio.run(main())
    else:
        print("\n(Skipping live run — pass --live to also exercise the real agent loop.)")