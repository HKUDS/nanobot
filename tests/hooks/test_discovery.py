"""Tests for hook plugin discovery via entry_points."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nanobot.hooks.center import HookCenter
from nanobot.hooks.discovery import discover_hook_plugins, register_discovered


@pytest.fixture
def center():
    c = HookCenter()
    c.register_point("session.before_save", "Before session save")
    c.register_point("tool.before_execute", "Before tool execution")
    return c


class TestDiscoverHookPlugins:
    def test_no_entry_points(self):
        with patch("importlib.metadata.entry_points", return_value=[]):
            result = discover_hook_plugins()
            assert result == {}

    def test_loads_valid_plugin(self):
        fake_ep = MagicMock()
        fake_ep.name = "my_plugin"
        fake_ep.load.return_value = lambda ctx: None

        with patch("importlib.metadata.entry_points", return_value=[fake_ep]):
            result = discover_hook_plugins()
            assert "my_plugin" in result

    def test_skips_failing_load(self):
        fake_ep = MagicMock()
        fake_ep.name = "bad_plugin"
        fake_ep.load.side_effect = ImportError("missing dep")

        with patch("importlib.metadata.entry_points", return_value=[fake_ep]):
            result = discover_hook_plugins()
            assert result == {}

    def test_loads_multiple_plugins(self):
        ep1 = MagicMock()
        ep1.name = "p1"
        ep1.load.return_value = lambda ctx: None

        ep2 = MagicMock()
        ep2.name = "p2"
        ep2.load.return_value = lambda ctx: None

        with patch("importlib.metadata.entry_points", return_value=[ep1, ep2]):
            result = discover_hook_plugins()
            assert len(result) == 2


class TestRegisterDiscovered:
    def test_dict_plugin_registers_per_point(self, center):
        handler = MagicMock(return_value=None)
        plugin = {"session.before_save": handler}

        with patch("nanobot.hooks.discovery.discover_hook_plugins", return_value={"p": plugin}):
            count = register_discovered(center)

        assert count == 1
        assert len(center.get_handlers("session.before_save")) == 1

    def test_callable_with_hook_points(self, center):
        async def handler(ctx) -> None:
            pass

        handler.hook_points = ["tool.before_execute"]

        with patch(
            "nanobot.hooks.discovery.discover_hook_plugins",
            return_value={"p": handler},
        ):
            count = register_discovered(center)

        assert count == 1
        assert len(center.get_handlers("tool.before_execute")) == 1

    def test_one_fails_other_succeeds(self, center):
        async def good(ctx):
            pass

        good.hook_points = ["session.before_save"]

        with patch(
            "nanobot.hooks.discovery.discover_hook_plugins",
            return_value={"bad": 42, "good": good},
        ):
            count = register_discovered(center)

        assert count == 1
        assert len(center.get_handlers("session.before_save")) == 1

    def test_empty_discovery(self, center):
        with patch("nanobot.hooks.discovery.discover_hook_plugins", return_value={}):
            count = register_discovered(center)
        assert count == 0

    def test_callable_without_hook_points_logs_warning(self, center):
        async def handler(ctx):
            pass

        with patch(
            "nanobot.hooks.discovery.discover_hook_plugins",
            return_value={"no_points": handler},
        ):
            count = register_discovered(center)

        assert count == 0

    def test_callable_with_empty_hook_points_skipped(self, center):
        async def handler(ctx):
            pass

        handler.hook_points = []

        with patch(
            "nanobot.hooks.discovery.discover_hook_plugins",
            return_value={"empty_points": handler},
        ):
            count = register_discovered(center)

        assert count == 0
