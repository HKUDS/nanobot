"""Tests for reasoning_content preservation in message sanitization.

Kimi K2.5 and DeepSeek-R1 return reasoning_content in assistant messages.
When the model uses thinking/reasoning mode with tool calls, the API requires
reasoning_content to be echoed back in subsequent requests. Stripping it
causes: "thinking is enabled but reasoning_content is missing in assistant
tool call message".
"""

from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.agent.context import ContextBuilder
from pathlib import Path


def test_sanitize_preserves_reasoning_content() -> None:
    """reasoning_content must survive _sanitize_messages for thinking models."""
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "What is 2+2?"},
        {
            "role": "assistant",
            "content": "The answer is 4.",
            "reasoning_content": "Let me think... 2+2=4",
        },
    ]
    sanitized = LiteLLMProvider._sanitize_messages(messages)
    assistant_msg = sanitized[2]
    assert assistant_msg["reasoning_content"] == "Let me think... 2+2=4"


def test_sanitize_preserves_reasoning_content_with_tool_calls() -> None:
    """reasoning_content on assistant tool-call messages must be preserved.

    This is the exact scenario that triggers the Kimi error — the assistant
    returns reasoning_content alongside tool_calls, and the next request
    must include both.
    """
    messages = [
        {"role": "user", "content": "Search for nanobot"},
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "I should search the web for nanobot info.",
            "tool_calls": [
                {
                    "id": "call_123",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": '{"query": "nanobot"}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_123",
            "name": "web_search",
            "content": "nanobot is an AI assistant",
        },
    ]
    sanitized = LiteLLMProvider._sanitize_messages(messages)
    assistant_msg = sanitized[1]
    assert "reasoning_content" in assistant_msg
    assert assistant_msg["reasoning_content"] == "I should search the web for nanobot info."
    assert "tool_calls" in assistant_msg


def test_sanitize_still_strips_unknown_keys() -> None:
    """Non-standard keys other than reasoning_content should still be stripped."""
    messages = [
        {
            "role": "assistant",
            "content": "hello",
            "some_random_field": "should be removed",
            "another_unknown": 42,
        },
    ]
    sanitized = LiteLLMProvider._sanitize_messages(messages)
    assert "some_random_field" not in sanitized[0]
    assert "another_unknown" not in sanitized[0]
    assert sanitized[0]["content"] == "hello"


def test_sanitize_handles_missing_reasoning_content() -> None:
    """Messages without reasoning_content should work as before (no regression)."""
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "thanks"},
    ]
    sanitized = LiteLLMProvider._sanitize_messages(messages)
    assert len(sanitized) == 3
    assert "reasoning_content" not in sanitized[1]
    assert sanitized[1]["content"] == "hello"


def test_context_builder_adds_reasoning_content() -> None:
    """ContextBuilder.add_assistant_message should include reasoning_content."""
    builder = ContextBuilder(Path("/tmp"))
    messages: list = []

    tool_calls = [
        {"id": "call_1", "type": "function", "function": {"name": "exec", "arguments": "{}"}}
    ]
    messages = builder.add_assistant_message(
        messages, "running command", tool_calls, reasoning_content="Let me run this command."
    )
    assert len(messages) == 1
    assert messages[0]["reasoning_content"] == "Let me run this command."
    assert messages[0]["tool_calls"] == tool_calls


def test_context_builder_omits_reasoning_content_when_none() -> None:
    """When reasoning_content is None, it should not appear in the message."""
    builder = ContextBuilder(Path("/tmp"))
    messages: list = []
    messages = builder.add_assistant_message(messages, "hello", reasoning_content=None)
    assert "reasoning_content" not in messages[0]
