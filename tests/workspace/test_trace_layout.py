"""Tests for TraceHook with WorkspaceLayout."""

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nanobot.agent.hook import TraceHook, AgentHookContext
from nanobot.workspace.layout import WorkspaceLayout


@dataclass
class FakeResponse:
    content: str = "world"
    finish_reason: str = "stop"
    reasoning_content: str | None = None
    thinking_blocks: list | None = None


@dataclass
class FakeToolCall:
    id: str = "call_1"
    name: str = "test"
    arguments: str = "{}"


@dataclass
class FakeContext:
    messages: list[dict[str, Any]] = field(default_factory=lambda: [{"role": "user", "content": "hello"}])
    iteration: int = 0
    response: FakeResponse = field(default_factory=FakeResponse)
    tool_calls: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)
    tool_events: list = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 10, "completion_tokens": 5})
    final_content: str = "world"
    stop_reason: str = "completed"
    error: str | None = None


def test_trace_writes_to_log_path(tmp_path: Path):
    layout = WorkspaceLayout(workspace=tmp_path, channel="discord", channel_name="develop", chat_id="147xxx")
    layout.ensure_dirs()

    log_file = tmp_path / "test.jsonl"
    hook = TraceHook(log_path=log_file)
    hook.session_key = "discord:147xxx"

    ctx = FakeContext()
    asyncio.run(hook.before_iteration(ctx))
    asyncio.run(hook.after_iteration(ctx))

    assert log_file.exists()
    entry = json.loads(log_file.read_text().strip())
    assert entry["session_key"] == "discord:147xxx"
    assert entry["request"][0]["role"] == "user"


def test_trace_sanitizes_base64_images(tmp_path: Path):
    """Base64 image data should be replaced with placeholders."""
    log_file = tmp_path / "test.jsonl"
    hook = TraceHook(log_path=log_file)
    hook.session_key = "test:123"

    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "Look at this:"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,ABC123"}, "_meta": {"path": "/tmp/img.png"}},
        ]
    }]
    ctx = FakeContext(messages=messages)
    asyncio.run(hook.before_iteration(ctx))
    asyncio.run(hook.after_iteration(ctx))

    entry = json.loads(log_file.read_text().strip())
    sanitized_content = entry["request"][0]["content"]
    assert sanitized_content[0] == {"type": "text", "text": "Look at this:"}
    assert sanitized_content[1] == {"type": "text", "text": "[image: /tmp/img.png]"}


def test_trace_no_truncation(tmp_path: Path):
    """Messages should not be truncated."""
    log_file = tmp_path / "test.jsonl"
    hook = TraceHook(log_path=log_file)
    hook.session_key = "test:123"

    long_content = "x" * 10000
    messages = [{"role": "user", "content": long_content}]
    ctx = FakeContext(messages=messages)
    asyncio.run(hook.before_iteration(ctx))
    asyncio.run(hook.after_iteration(ctx))

    entry = json.loads(log_file.read_text().strip())
    assert entry["request"][0]["content"] == long_content
    assert "[truncated]" not in entry["request"][0]["content"]
