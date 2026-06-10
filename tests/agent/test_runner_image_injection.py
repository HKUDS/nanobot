"""Tests for the model-agnostic tool-screenshot delivery mechanism.

A tool that needs the model to *see* an image returns a list of content blocks
containing ``image_url`` blocks. The runner pulls those out of the tool result
(keeping the ``tool`` message text-only, since most providers reject images in
tool-role messages) and delivers them as a follow-up ``user`` message — the
universal path that works across every vision provider.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars

_IMG = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}


class TestSplitToolResultMedia:
    """Unit tests for AgentRunner._split_tool_result_media (pure function)."""

    def test_plain_string_passes_through(self):
        assert AgentRunner._split_tool_result_media("hello") == ("hello", [])

    def test_non_list_non_str_passes_through(self):
        assert AgentRunner._split_tool_result_media(None) == (None, [])
        sentinel = {"some": "dict"}
        text, images = AgentRunner._split_tool_result_media(sentinel)
        assert text is sentinel and images == []

    def test_text_only_list_is_unchanged(self):
        blocks = [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
        text, images = AgentRunner._split_tool_result_media(blocks)
        # No images -> return the original object untouched, no behaviour change.
        assert text is blocks
        assert images == []

    def test_image_plus_text_is_split(self):
        text, images = AgentRunner._split_tool_result_media(
            [_IMG, {"type": "text", "text": "clicked at 10,20"}]
        )
        assert text == "clicked at 10,20"
        assert images == [_IMG]

    def test_image_only_yields_empty_text(self):
        text, images = AgentRunner._split_tool_result_media([_IMG])
        assert text == ""
        assert images == [_IMG]

    def test_multiple_text_segments_are_joined(self):
        text, images = AgentRunner._split_tool_result_media(
            [{"type": "text", "text": "one"}, _IMG, {"type": "text", "text": "two"}]
        )
        assert text == "one\ntwo"
        assert images == [_IMG]

    def test_multiple_images_are_all_collected(self):
        text, images = AgentRunner._split_tool_result_media([_IMG, _IMG])
        assert images == [_IMG, _IMG]


@pytest.mark.asyncio
async def test_runner_delivers_tool_screenshot_as_followup_user_message():
    """End-to-end: a tool returning an image_url block results in a text-only
    tool message plus a follow-up user message carrying the screenshot."""
    captured_second_call: list[dict] = []
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="taking a screenshot",
                tool_calls=[
                    ToolCallRequest(id="cu1", name="computer_use", arguments={"action": "screenshot"})
                ],
                usage={},
            )
        captured_second_call[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider = MagicMock()
    provider.chat_with_retry = chat_with_retry

    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value=[_IMG, {"type": "text", "text": "clicked"}])

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "look at the screen"}],
        tools=tools,
        model="test-model",
        max_iterations=4,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "done"

    # 1) The tool-role message is text-only; the image did NOT leak into it.
    tool_msgs = [
        m for m in captured_second_call
        if m.get("role") == "tool" and m.get("tool_call_id") == "cu1"
    ]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"] == "clicked"

    # 2) A follow-up user message carries the screenshot image_url block...
    user_img_msgs = [
        m for m in captured_second_call
        if m.get("role") == "user" and isinstance(m.get("content"), list)
        and any(isinstance(b, dict) and b.get("type") == "image_url" for b in m["content"])
    ]
    assert user_img_msgs, "expected a user message carrying the screenshot image_url block"

    # 3) ...and it appears after the tool result (so the model sees the action then its effect).
    assert captured_second_call.index(user_img_msgs[-1]) > captured_second_call.index(tool_msgs[0])


@pytest.mark.asyncio
async def test_runner_unchanged_for_text_only_tools():
    """A plain text tool result must not trigger any extra user message."""
    captured_second_call: list[dict] = []
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCallRequest(id="t1", name="web_search", arguments={"query": "x"})],
                usage={},
            )
        captured_second_call[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider = MagicMock()
    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="plain text result")

    runner = AgentRunner(provider)
    await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "search"}],
        tools=tools,
        model="test-model",
        max_iterations=4,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    # No image -> no user message with a list/image content was injected.
    injected_user_imgs = [
        m for m in captured_second_call
        if m.get("role") == "user" and isinstance(m.get("content"), list)
        and any(isinstance(b, dict) and b.get("type") == "image_url" for b in m["content"])
    ]
    assert injected_user_imgs == []
