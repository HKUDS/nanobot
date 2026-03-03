"""Tests for cache-friendly prompt construction."""

from __future__ import annotations

from datetime import datetime as real_datetime
from pathlib import Path
import datetime as datetime_module

from nanobot.agent.context import ContextBuilder
from nanobot.providers.openai_codex_provider import _prompt_cache_key


class _FakeDatetime(real_datetime):
    current = real_datetime(2026, 2, 24, 13, 59)

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return cls.current


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    return workspace


def test_system_prompt_stays_stable_when_clock_changes(tmp_path, monkeypatch) -> None:
    """System prompt should not change just because wall clock minute changes."""
    monkeypatch.setattr(datetime_module, "datetime", _FakeDatetime)

    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    _FakeDatetime.current = real_datetime(2026, 2, 24, 13, 59)
    prompt1 = builder.build_system_prompt()

    _FakeDatetime.current = real_datetime(2026, 2, 24, 14, 0)
    prompt2 = builder.build_system_prompt()

    assert prompt1 == prompt2


def test_runtime_context_is_separate_untrusted_user_message(tmp_path) -> None:
    """Runtime metadata should be a separate user message before the actual user message."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    messages = builder.build_messages(
        history=[],
        current_message="Return exactly: OK",
        channel="cli",
        chat_id="direct",
    )

    assert messages[0]["role"] == "system"
    assert "## Current Session" not in messages[0]["content"]

    assert messages[-2]["role"] == "user"
    runtime_content = messages[-2]["content"]
    assert isinstance(runtime_content, str)
    assert ContextBuilder._RUNTIME_CONTEXT_TAG in runtime_content
    assert "Current Time:" in runtime_content
    assert "Channel: cli" in runtime_content
    assert "Chat ID: direct" in runtime_content

    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "Return exactly: OK"


def test_codex_prompt_cache_key_ignores_runtime_clock_line() -> None:
    """Changing only runtime Current Time should not change prompt_cache_key."""
    tag = ContextBuilder._RUNTIME_CONTEXT_TAG

    m1 = [
        {"role": "system", "content": "sys"},
        {
            "role": "user",
            "content": f"{tag}\nCurrent Time: 2026-02-27 10:00 (Friday)\nChannel: cli\nChat ID: direct",
        },
        {"role": "user", "content": "Summarize latest logs"},
    ]
    m2 = [
        {"role": "system", "content": "sys"},
        {
            "role": "user",
            "content": f"{tag}\nCurrent Time: 2026-02-27 10:01 (Friday)\nChannel: cli\nChat ID: direct",
        },
        {"role": "user", "content": "Summarize latest logs"},
    ]

    assert _prompt_cache_key(m1) == _prompt_cache_key(m2)


def test_codex_prompt_cache_key_includes_model_and_tools() -> None:
    """Different model/tools should produce a different prompt_cache_key."""
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello"}]
    tools_a = [{"type": "function", "name": "read_file", "parameters": {"type": "object"}}]
    tools_b = [{"type": "function", "name": "write_file", "parameters": {"type": "object"}}]

    k1 = _prompt_cache_key(messages, model="gpt-5.1-codex", tools=tools_a)
    k2 = _prompt_cache_key(messages, model="gpt-5.1-codex-mini", tools=tools_a)
    k3 = _prompt_cache_key(messages, model="gpt-5.1-codex", tools=tools_b)

    assert k1 != k2
    assert k1 != k3
