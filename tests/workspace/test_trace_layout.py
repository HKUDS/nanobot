"""Tests for TraceHook with WorkspaceLayout."""

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from nanobot.agent.trace import TraceHook
from nanobot.workspace.layout import WorkspaceLayout


@dataclass
class FakeResponse:
    content: str = "world"
    finish_reason: str = "stop"


@dataclass
class FakeToolCall:
    name: str = "test"
    arguments: str = "{}"


@dataclass
class FakeContext:
    messages: list[dict[str, Any]] = field(default_factory=lambda: [{"role": "user", "content": "hello"}])
    iteration: int = 0
    response: FakeResponse = field(default_factory=FakeResponse)
    tool_calls: list = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 10, "completion_tokens": 5})


def test_trace_writes_to_log_path(tmp_path: Path):
    layout = WorkspaceLayout(workspace=tmp_path, channel="discord", channel_name="develop", chat_id="147xxx")
    layout.ensure_dirs()

    hook = TraceHook(llm_logs_dir=layout.llm_logs_dir)
    hook.session_key = "discord:147xxx"
    hook.set_log_path(layout.llm_log_path("2026-04-01", 1))

    ctx = FakeContext()
    asyncio.run(hook.before_iteration(ctx))
    asyncio.run(hook.after_iteration(ctx))

    log_path = layout.llm_log_path("2026-04-01", 1)
    assert log_path.exists()
    entry = json.loads(log_path.read_text().strip())
    assert entry["session_key"] == "discord:147xxx"


def test_trace_fallback_to_dir(tmp_path: Path):
    """Without set_log_path, falls back to _log_dir/{session_key}.jsonl."""
    hook = TraceHook(llm_logs_dir=tmp_path)
    hook.session_key = "discord:147xxx"

    ctx = FakeContext()
    asyncio.run(hook.before_iteration(ctx))
    asyncio.run(hook.after_iteration(ctx))

    path = tmp_path / "discord_147xxx.jsonl"
    assert path.exists()


def test_trace_legacy_traces_dir(tmp_path: Path):
    """Legacy traces_dir= kwarg still works."""
    hook = TraceHook(traces_dir=tmp_path)
    hook.session_key = "test:123"

    ctx = FakeContext()
    asyncio.run(hook.before_iteration(ctx))
    asyncio.run(hook.after_iteration(ctx))

    path = tmp_path / "test_123.jsonl"
    assert path.exists()
