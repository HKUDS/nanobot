"""Tests for dynamic prompt injection via hooks."""

import json
import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.agent.hooks import Hook, HookEvent, HookRegistry, HookResult, SkillsEnabledFilter
from nanobot.agent.hooks.json_loader import JsonConfigHook


# ---- Test helpers ----

class InjectingHook(Hook):
    """Hook that injects a string for prompt_injection events."""

    def __init__(self, name: str, content: str, priority: int = 100):
        self._name = name
        self._content = content
        self._priority = priority

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    def on_event(self, event: HookEvent, context: dict) -> HookResult:
        if event == HookEvent.PRE_BUILD_CONTEXT and context.get("type") == "prompt_injection":
            return HookResult(modified_data=self._content)
        return HookResult()


class BlockingInjectionHook(Hook):
    """Hook that blocks prompt_injection collection."""

    def __init__(self, name: str, priority: int = 100):
        self._name = name
        self._priority = priority

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    def on_event(self, event: HookEvent, context: dict) -> HookResult:
        if event == HookEvent.PRE_BUILD_CONTEXT and context.get("type") == "prompt_injection":
            return HookResult(proceed=False, reason="blocked")
        return HookResult()


class ExplodingHook(Hook):
    """Hook that raises on prompt_injection events."""

    @property
    def name(self) -> str:
        return "exploding"

    @property
    def priority(self) -> int:
        return 50

    def on_event(self, event: HookEvent, context: dict) -> HookResult:
        if event == HookEvent.PRE_BUILD_CONTEXT and context.get("type") == "prompt_injection":
            raise RuntimeError("boom")
        return HookResult()


# ---- Registry: collect_prompt_injections ----

def test_no_hooks_returns_empty():
    reg = HookRegistry()
    assert reg.collect_prompt_injections() == []


def test_single_hook_injection():
    reg = HookRegistry()
    reg.register(InjectingHook("h1", "Hello from hook"))
    result = reg.collect_prompt_injections(channel="general", chat_id="abc")
    assert result == ["Hello from hook"]


def test_multiple_hooks_accumulate():
    reg = HookRegistry()
    reg.register(InjectingHook("h1", "first", priority=10))
    reg.register(InjectingHook("h2", "second", priority=20))
    result = reg.collect_prompt_injections()
    assert result == ["first", "second"]


def test_proceed_false_stops_collection():
    reg = HookRegistry()
    reg.register(InjectingHook("h1", "before", priority=10))
    reg.register(BlockingInjectionHook("blocker", priority=50))
    reg.register(InjectingHook("h3", "after", priority=100))
    result = reg.collect_prompt_injections()
    assert result == ["before"]  # "after" never collected


def test_exception_does_not_break_collection():
    reg = HookRegistry()
    reg.register(ExplodingHook())  # priority=50
    reg.register(InjectingHook("safe", "ok", priority=100))
    result = reg.collect_prompt_injections()
    assert result == ["ok"]


def test_non_string_modified_data_ignored():
    """If a hook returns non-string modified_data, it's skipped."""

    class ListHook(Hook):
        @property
        def name(self): return "list_hook"
        def on_event(self, event, context):
            if event == HookEvent.PRE_BUILD_CONTEXT and context.get("type") == "prompt_injection":
                return HookResult(modified_data=["not", "a", "string"])
            return HookResult()

    reg = HookRegistry()
    reg.register(ListHook())
    assert reg.collect_prompt_injections() == []


def test_channel_and_chat_id_passed_to_hooks():
    """Verify channel/chat_id are in the context dict."""
    received = {}

    class SpyHook(Hook):
        @property
        def name(self): return "spy"
        def on_event(self, event, context):
            if event == HookEvent.PRE_BUILD_CONTEXT and context.get("type") == "prompt_injection":
                received.update(context)
            return HookResult()

    reg = HookRegistry()
    reg.register(SpyHook())
    reg.collect_prompt_injections(channel="support", chat_id="chat-42")
    assert received["channel"] == "support"
    assert received["chat_id"] == "chat-42"


# ---- SkillsEnabledFilter ignores prompt_injection ----

def test_skills_filter_ignores_prompt_injection():
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / "skills").mkdir()
        f = SkillsEnabledFilter(workspace)
        result = f.on_event(
            HookEvent.PRE_BUILD_CONTEXT,
            {"type": "prompt_injection", "channel": "", "chat_id": ""},
        )
        # Should return default (no modification, proceed=True)
        assert result.proceed
        assert result.modified_data is None


# ---- ContextBuilder: _collect_prompt_injections ----

def _make_builder(tmpdir: str) -> ContextBuilder:
    workspace = Path(tmpdir)
    (workspace / "skills").mkdir(exist_ok=True)
    (workspace / "memory").mkdir(exist_ok=True)
    return ContextBuilder(workspace)


def test_no_dynamic_context_without_hooks():
    with tempfile.TemporaryDirectory() as tmpdir:
        builder = _make_builder(tmpdir)
        prompt = builder.build_system_prompt()
        assert "<dynamic_context>" not in prompt


def test_dynamic_context_appears_in_prompt():
    with tempfile.TemporaryDirectory() as tmpdir:
        builder = _make_builder(tmpdir)
        builder.hooks.register(InjectingHook("h1", "injected content"))
        prompt = builder.build_system_prompt(channel="ch", chat_id="id")
        assert "<dynamic_context>" in prompt
        assert "injected content" in prompt
        assert "</dynamic_context>" in prompt


def test_truncation_at_limit():
    with tempfile.TemporaryDirectory() as tmpdir:
        builder = _make_builder(tmpdir)
        long_text = "x" * 5000
        builder.hooks.register(InjectingHook("big", long_text))
        prompt = builder.build_system_prompt(channel="c", chat_id="i")
        assert "... (truncated)" in prompt
        # The content inside dynamic_context should be capped
        start = prompt.index("<dynamic_context>\n") + len("<dynamic_context>\n")
        end = prompt.index("\n</dynamic_context>")
        inner = prompt[start:end]
        assert len(inner) <= 4000 + len("\n... (truncated)")


# ---- ContextBuilder: build_messages passes channel/chat_id ----

def test_build_messages_passes_channel_chat_id():
    with tempfile.TemporaryDirectory() as tmpdir:
        builder = _make_builder(tmpdir)
        builder.hooks.register(InjectingHook("h1", "from-hook"))
        messages = builder.build_messages(
            history=[], current_message="hi",
            channel="support", chat_id="chat-99",
        )
        system_content = messages[0]["content"]
        assert "from-hook" in system_content
        assert "<dynamic_context>" in system_content


# ---- JsonConfigHook: stdout capture + env vars ----

def test_json_hook_stdout_captured_for_prompt_injection():
    """A JSON hook that prints to stdout should have its output captured."""
    with tempfile.TemporaryDirectory() as tmpdir:
        script = Path(tmpdir) / "inject.sh"
        script.write_text('#!/bin/bash\necho "hello from script"\nexit 0\n')
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        hook = JsonConfigHook({
            "name": "test-inject",
            "event": "PreBuildContext",
            "command": str(script),
        })
        result = hook.on_event(
            HookEvent.PRE_BUILD_CONTEXT,
            {"type": "prompt_injection", "channel": "ch", "chat_id": "id"},
        )
        assert result.proceed
        assert result.modified_data == "hello from script"


def test_json_hook_no_capture_for_skills_type():
    """stdout should NOT be captured when type is 'skills'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        script = Path(tmpdir) / "inject.sh"
        script.write_text('#!/bin/bash\necho "should not capture"\nexit 0\n')
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        hook = JsonConfigHook({
            "name": "test-skills",
            "event": "PreBuildContext",
            "command": str(script),
        })
        result = hook.on_event(
            HookEvent.PRE_BUILD_CONTEXT,
            {"type": "skills", "data": []},
        )
        assert result.modified_data is None


def test_json_hook_env_vars_for_prompt_injection():
    """Verify CONTEXT_TYPE, CHANNEL, CHAT_ID are passed as env vars."""
    with tempfile.TemporaryDirectory() as tmpdir:
        script = Path(tmpdir) / "env_check.sh"
        script.write_text(
            '#!/bin/bash\n'
            'echo "type=$CONTEXT_TYPE chan=$CHANNEL cid=$CHAT_ID"\n'
            'exit 0\n'
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        hook = JsonConfigHook({
            "name": "env-check",
            "event": "PreBuildContext",
            "command": str(script),
        })
        result = hook.on_event(
            HookEvent.PRE_BUILD_CONTEXT,
            {"type": "prompt_injection", "channel": "eng", "chat_id": "c-1"},
        )
        assert result.modified_data == "type=prompt_injection chan=eng cid=c-1"


def test_json_hook_empty_stdout_no_injection():
    """Empty stdout should not produce an injection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        script = Path(tmpdir) / "empty.sh"
        script.write_text('#!/bin/bash\nexit 0\n')
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        hook = JsonConfigHook({
            "name": "empty",
            "event": "PreBuildContext",
            "command": str(script),
        })
        result = hook.on_event(
            HookEvent.PRE_BUILD_CONTEXT,
            {"type": "prompt_injection", "channel": "", "chat_id": ""},
        )
        assert result.modified_data is None
