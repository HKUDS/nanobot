"""Tests for nanobot.agent.hooks_registry.discover_hooks and AgentHookContext routing fields."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.hooks_registry import discover_hooks


# ---------------------------------------------------------------------------
# discover_hooks: empty entry points
# ---------------------------------------------------------------------------


def test_discover_hooks_empty() -> None:
    """No entry points registered → returns empty list."""
    with patch("nanobot.agent.hooks_registry.entry_points") as mock_ep:
        mock_ep.return_value = []
        result = discover_hooks()
    assert result == []


# ---------------------------------------------------------------------------
# discover_hooks: class pattern
# ---------------------------------------------------------------------------


def test_discover_hooks_class_pattern() -> None:
    """Entry point returns an AgentHook subclass → instantiates it."""

    class MyHook(AgentHook):
        pass

    mock_entry = MagicMock()
    mock_entry.name = "my-hook"
    mock_entry.load.return_value = MyHook

    with patch("nanobot.agent.hooks_registry.entry_points") as mock_ep:
        mock_ep.return_value = [mock_entry]
        result = discover_hooks()

    assert len(result) == 1
    assert isinstance(result[0], MyHook)
    assert isinstance(result[0], AgentHook)


# ---------------------------------------------------------------------------
# discover_hooks: instance pattern
# ---------------------------------------------------------------------------


def test_discover_hooks_instance_pattern() -> None:
    """Entry point returns an AgentHook instance → uses it directly."""

    instance = AgentHook()

    mock_entry = MagicMock()
    mock_entry.name = "my-instance-hook"
    mock_entry.load.return_value = instance

    with patch("nanobot.agent.hooks_registry.entry_points") as mock_ep:
        mock_ep.return_value = [mock_entry]
        result = discover_hooks()

    assert len(result) == 1
    assert result[0] is instance


# ---------------------------------------------------------------------------
# discover_hooks: factory pattern
# ---------------------------------------------------------------------------


def test_discover_hooks_factory_pattern() -> None:
    """Entry point returns a callable that returns an AgentHook → calls it."""

    class FactoryHook(AgentHook):
        pass

    mock_entry = MagicMock()
    mock_entry.name = "my-factory-hook"
    mock_entry.load.return_value = FactoryHook  # class is callable, but not isinstance(AgentHook) — wait...

    # Actually, a class *is* isinstance(type) and issubclass(AgentHook), so it
    # would hit the class branch. Use a plain function instead.
    def factory() -> AgentHook:
        return FactoryHook()

    mock_entry.load.return_value = factory

    with patch("nanobot.agent.hooks_registry.entry_points") as mock_ep:
        mock_ep.return_value = [mock_entry]
        result = discover_hooks()

    assert len(result) == 1
    assert isinstance(result[0], FactoryHook)


# ---------------------------------------------------------------------------
# discover_hooks: factory returns non-hook
# ---------------------------------------------------------------------------


def test_discover_hooks_factory_bad_return() -> None:
    """Factory returns a non-AgentHook → logs warning, skips entry."""

    def bad_factory():
        return "not a hook"

    mock_entry = MagicMock()
    mock_entry.name = "bad-factory"
    mock_entry.load.return_value = bad_factory

    with patch("nanobot.agent.hooks_registry.entry_points") as mock_ep:
        mock_ep.return_value = [mock_entry]
        result = discover_hooks()

    assert result == []


# ---------------------------------------------------------------------------
# discover_hooks: load error
# ---------------------------------------------------------------------------


def test_discover_hooks_load_error() -> None:
    """Entry point raises during load → logs exception, continues to next."""

    class GoodHook(AgentHook):
        pass

    bad_entry = MagicMock()
    bad_entry.name = "broken-hook"
    bad_entry.load.side_effect = RuntimeError("import exploded")

    good_entry = MagicMock()
    good_entry.name = "good-hook"
    good_entry.load.return_value = GoodHook

    with patch("nanobot.agent.hooks_registry.entry_points") as mock_ep:
        mock_ep.return_value = [bad_entry, good_entry]
        result = discover_hooks()

    assert len(result) == 1
    assert isinstance(result[0], GoodHook)


# ---------------------------------------------------------------------------
# discover_hooks: invalid type (not class, not instance, not callable)
# ---------------------------------------------------------------------------


def test_discover_hooks_invalid_type() -> None:
    """Entry point returns an int → logs warning, skips entry."""

    mock_entry = MagicMock()
    mock_entry.name = "weird-hook"
    mock_entry.load.return_value = 42

    with patch("nanobot.agent.hooks_registry.entry_points") as mock_ep:
        mock_ep.return_value = [mock_entry]
        result = discover_hooks()

    assert result == []


# ---------------------------------------------------------------------------
# AgentHookContext routing fields
# ---------------------------------------------------------------------------


def test_agent_hook_context_routing_fields() -> None:
    """Default values are set correctly and fields are mutable."""
    ctx = AgentHookContext(iteration=1, messages=[])

    # Defaults
    assert ctx.channel == "cli"
    assert ctx.chat_id == "direct"
    assert ctx.session_key is None
    assert ctx.message_id is None
    assert ctx.sender_id is None

    # Assignment
    ctx.channel = "slack"
    ctx.chat_id = "C123"
    ctx.session_key = "slack:C123"
    ctx.message_id = "msg1"
    ctx.sender_id = "U123"

    assert ctx.channel == "slack"
    assert ctx.chat_id == "C123"
    assert ctx.session_key == "slack:C123"
    assert ctx.message_id == "msg1"
    assert ctx.sender_id == "U123"


def test_agent_hook_context_other_defaults() -> None:
    """Non-routing fields also have correct defaults."""
    ctx = AgentHookContext(iteration=0, messages=[])

    assert ctx.response is None
    assert ctx.usage == {}
    assert ctx.tool_calls == []
    assert ctx.tool_results == []
    assert ctx.tool_events == []
    assert ctx.final_content is None
    assert ctx.stop_reason is None
    assert ctx.error is None
