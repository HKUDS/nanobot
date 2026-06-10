"""Integration test: the real computer_use tool driven through the AgentRunner loop.

No real model, browser, or desktop is involved — a scripted provider issues
computer_use tool calls and a fake backend serves screenshots. This verifies the
whole path wires up: runner -> real ComputerUseTool.execute -> backend -> image
content blocks -> runner splits them -> screenshots delivered to the model as
follow-up user messages across a multi-step loop, while tool messages stay
text-only (so OpenAI-compatible providers, i.e. OpenRouter, accept them).
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest

from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.computer_use import ComputerUseTool
from nanobot.agent.tools.computer_use_backends.base import ComputerBackend
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, ToolCallRequest

_MAX = AgentDefaults().max_tool_result_chars


class _FakeBackend(ComputerBackend):
    environment = "desktop"

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def dimensions(self):
        return (1280, 800)

    async def screenshot(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (1280, 800), (0, 0, 0)).save(buf, format="PNG")
        return buf.getvalue()

    async def click(self, x, y, button="left", count=1):
        self.calls.append(("click", x, y, button, count))

    async def move(self, x, y):
        self.calls.append(("move", x, y))

    async def drag(self, x, y):
        self.calls.append(("drag", x, y))

    async def scroll(self, x, y, direction, amount):
        self.calls.append(("scroll", x, y, direction, amount))

    async def type_text(self, text):
        self.calls.append(("type", text))

    async def key(self, combo):
        self.calls.append(("key", combo))


@pytest.mark.asyncio
async def test_computer_use_loop_feeds_screenshots_back_to_model():
    fb = _FakeBackend()
    tool = ComputerUseTool(backend_impl=fb, target_width=1280, target_height=800)
    tools = ToolRegistry()
    tools.register(tool)

    captured: list[dict] = []
    step = {"i": 0}

    async def chat_with_retry(*, messages, **kwargs):
        step["i"] += 1
        if step["i"] == 1:
            return LLMResponse(
                content="let me look",
                tool_calls=[ToolCallRequest(id="a", name="computer_use", arguments={"action": "screenshot"})],
                usage={},
            )
        if step["i"] == 2:
            return LLMResponse(
                content="clicking submit",
                tool_calls=[
                    ToolCallRequest(
                        id="b", name="computer_use",
                        arguments={"action": "left_click", "x": 100, "y": 50},
                    )
                ],
                usage={},
            )
        captured[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider = MagicMock()
    provider.chat_with_retry = chat_with_retry

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "open the screen and click submit"}],
        tools=tools,
        model="test-model",
        max_iterations=6,
        max_tool_result_chars=_MAX,
    ))

    assert result.final_content == "done"

    # The backend received the click at identity scale (real == target == 1280x800).
    assert ("click", 100, 50, "left", 1) in fb.calls

    # Each computer_use call delivered a screenshot to the model as a user message.
    user_img_msgs = [
        m for m in captured
        if m.get("role") == "user" and isinstance(m.get("content"), list)
        and any(isinstance(b, dict) and b.get("type") == "image_url" for b in m["content"])
    ]
    assert len(user_img_msgs) >= 2

    # Tool-role messages stayed text-only (no image leaked into a tool message).
    tool_msgs = [m for m in captured if m.get("role") == "tool"]
    assert tool_msgs
    assert all(isinstance(m["content"], str) for m in tool_msgs)
