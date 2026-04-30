"""Tests for HookCenter entry-point plugin discovery."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from nanobot.hooks.center import HookCenter
from nanobot.hooks.discovery import discover_hook_plugins, register_discovered
from nanobot.hooks.event_types import (
    AfterIteration,
    BeforeExecuteTools,
    BeforeIteration,
)

_EP_TARGET = "importlib.metadata.entry_points"


def _make_entry_point(name: str, handler):
    ep = SimpleNamespace(name=name, load=lambda _h=handler: _h)
    return ep


def _make_entry_point_with_error(name: str):
    def _boom():
        raise ImportError(f"cannot import {name}")

    ep = SimpleNamespace(name=name, load=_boom)
    return ep


# ---------------------------------------------------------------------------
# discover_hook_plugins
# ---------------------------------------------------------------------------


def test_discover_returns_empty_dict_for_no_entry_points():
    with patch(_EP_TARGET, return_value=[]):
        result = discover_hook_plugins()

    assert result == {}


def test_discover_loads_single_plugin():
    handler = object()

    with patch(_EP_TARGET, return_value=[_make_entry_point("my_plugin", handler)]):
        result = discover_hook_plugins()

    assert result == {"my_plugin": handler}


def test_discover_loads_multiple_plugins():
    h1, h2 = object(), object()

    with patch(
        _EP_TARGET,
        return_value=[_make_entry_point("a", h1), _make_entry_point("b", h2)],
    ):
        result = discover_hook_plugins()

    assert result == {"a": h1, "b": h2}


def test_discover_skips_failed_plugin_loads_others():
    h2 = object()

    with patch(
        _EP_TARGET,
        return_value=[
            _make_entry_point_with_error("broken"),
            _make_entry_point("ok", h2),
        ],
    ):
        result = discover_hook_plugins()

    assert "broken" not in result
    assert result == {"ok": h2}


# ---------------------------------------------------------------------------
# register_discovered — happy path
# ---------------------------------------------------------------------------


def test_register_discovered_registers_handler():
    center = HookCenter()
    handler = Mock(return_value=None)
    handler.hook_events = [(BeforeIteration, "guard")]

    with patch(
        _EP_TARGET,
        return_value=[_make_entry_point("testguard", handler)],
    ):
        register_discovered(center)

    external = center._external_handlers
    assert BeforeIteration in external
    assert external[BeforeIteration]["guard"] == [handler]


def test_register_discovered_registers_multiple_plugins():
    center = HookCenter()
    h1 = Mock(return_value=None)
    h1.hook_events = [(BeforeIteration, "guard")]
    h2 = Mock(return_value=None)
    h2.hook_events = [(BeforeIteration, "observe")]

    with patch(
        _EP_TARGET,
        return_value=[
            _make_entry_point("g", h1),
            _make_entry_point("o", h2),
        ],
    ):
        register_discovered(center)

    external = center._external_handlers
    assert external[BeforeIteration]["guard"] == [h1]
    assert external[BeforeIteration]["observe"] == [h2]


def test_register_discovered_plugin_subscribes_multiple_event_types():
    center = HookCenter()
    handler = Mock(return_value=None)
    handler.hook_events = [
        (BeforeIteration, "guard"),
        (AfterIteration, "observe"),
    ]

    with patch(
        _EP_TARGET,
        return_value=[_make_entry_point("multi", handler)],
    ):
        register_discovered(center)

    external = center._external_handlers
    assert external[BeforeIteration]["guard"] == [handler]
    assert external[AfterIteration]["observe"] == [handler]


def test_register_discovered_multiple_plugins_same_event():
    center = HookCenter()
    h1 = Mock(return_value=None)
    h1.hook_events = [(BeforeIteration, "observe")]
    h2 = Mock(return_value=None)
    h2.hook_events = [(BeforeIteration, "observe")]

    with patch(
        _EP_TARGET,
        return_value=[
            _make_entry_point("p1", h1),
            _make_entry_point("p2", h2),
        ],
    ):
        register_discovered(center)

    external = center._external_handlers
    assert external[BeforeIteration]["observe"] == [h1, h2]


# ---------------------------------------------------------------------------
# register_discovered — allowlist
# ---------------------------------------------------------------------------


def test_register_discovered_respects_enabled_plugins_allowlist():
    center = HookCenter()
    allowed = Mock(return_value=None)
    allowed.hook_events = [(BeforeIteration, "observe")]
    blocked = Mock(return_value=None)
    blocked.hook_events = [(BeforeIteration, "observe")]

    config = SimpleNamespace(
        hooks=SimpleNamespace(enabled_plugins=["allowed_plugin"]),
    )

    with patch(
        _EP_TARGET,
        return_value=[
            _make_entry_point("allowed_plugin", allowed),
            _make_entry_point("blocked_plugin", blocked),
        ],
    ):
        register_discovered(center, config)

    external = center._external_handlers
    assert external[BeforeIteration]["observe"] == [allowed]
    assert blocked not in external.get(BeforeIteration, {}).get("observe", [])


def test_register_discovered_allowlist_none_allows_all():
    center = HookCenter()
    h1 = Mock(return_value=None)
    h1.hook_events = [(BeforeIteration, "observe")]
    h2 = Mock(return_value=None)
    h2.hook_events = [(BeforeIteration, "observe")]

    config = SimpleNamespace(hooks=SimpleNamespace(enabled_plugins=None))

    with patch(
        _EP_TARGET,
        return_value=[
            _make_entry_point("p1", h1),
            _make_entry_point("p2", h2),
        ],
    ):
        register_discovered(center, config)

    external = center._external_handlers
    assert external[BeforeIteration]["observe"] == [h1, h2]


def test_register_discovered_no_hooks_config_allows_all():
    center = HookCenter()
    handler = Mock(return_value=None)
    handler.hook_events = [(BeforeIteration, "observe")]

    config = SimpleNamespace()

    with patch(
        _EP_TARGET,
        return_value=[_make_entry_point("p", handler)],
    ):
        register_discovered(center, config)

    external = center._external_handlers
    assert external[BeforeIteration]["observe"] == [handler]


def test_register_discovered_no_config_allows_all():
    center = HookCenter()
    handler = Mock(return_value=None)
    handler.hook_events = [(BeforeIteration, "observe")]

    with patch(
        _EP_TARGET,
        return_value=[_make_entry_point("p", handler)],
    ):
        register_discovered(center)

    external = center._external_handlers
    assert external[BeforeIteration]["observe"] == [handler]


# ---------------------------------------------------------------------------
# register_discovered — edge cases
# ---------------------------------------------------------------------------


def test_register_discovered_empty_entry_points_noop():
    center = HookCenter()

    with patch(_EP_TARGET, return_value=[]):
        register_discovered(center)

    assert center._external_handlers == {}


def test_register_discovered_skips_plugin_without_hook_events():
    center = HookCenter()
    handler = object()

    with patch(
        _EP_TARGET,
        return_value=[_make_entry_point("noevents", handler)],
    ):
        register_discovered(center)

    assert center._external_handlers == {}


# ---------------------------------------------------------------------------
# register_discovered — error paths
# ---------------------------------------------------------------------------


def test_register_discovered_single_plugin_load_error_skips_and_continues():
    center = HookCenter()
    ok_handler = Mock(return_value=None)
    ok_handler.hook_events = [(BeforeExecuteTools, "transform")]

    with patch(
        _EP_TARGET,
        return_value=[
            _make_entry_point_with_error("bad"),
            _make_entry_point("good", ok_handler),
        ],
    ):
        register_discovered(center)

    external = center._external_handlers
    assert BeforeExecuteTools in external
    assert external[BeforeExecuteTools]["transform"] == [ok_handler]


def test_register_discovered_entry_points_raises_no_handlers_registered():
    center = HookCenter()

    def _fail(group):
        raise RuntimeError("metadata not available")

    with patch(_EP_TARGET, side_effect=_fail):
        register_discovered(center)

    assert center._external_handlers == {}


# ---------------------------------------------------------------------------
# HookCenter.discover integration
# ---------------------------------------------------------------------------


def test_center_discover_delegates_to_register_discovered():
    center = HookCenter()
    handler = Mock(return_value=None)
    handler.hook_events = [(BeforeIteration, "guard")]

    with patch(
        _EP_TARGET,
        return_value=[_make_entry_point("p", handler)],
    ):
        center.discover()

    external = center._external_handlers
    assert external[BeforeIteration]["guard"] == [handler]


def test_center_discover_with_config():
    center = HookCenter()
    allowed = Mock(return_value=None)
    allowed.hook_events = [(BeforeIteration, "observe")]
    blocked = Mock(return_value=None)
    blocked.hook_events = [(BeforeIteration, "observe")]

    config = SimpleNamespace(
        hooks=SimpleNamespace(enabled_plugins=["allowed"]),
    )

    with patch(
        _EP_TARGET,
        return_value=[
            _make_entry_point("allowed", allowed),
            _make_entry_point("blocked", blocked),
        ],
    ):
        center.discover(config)

    external = center._external_handlers
    assert external[BeforeIteration]["observe"] == [allowed]


def test_center_discover_does_not_prevent_agent_startup_on_error():
    center = HookCenter()

    def _fail(group):
        raise RuntimeError("metadata unavailable")

    with patch(_EP_TARGET, side_effect=_fail):
        center.discover()

    assert center._external_handlers == {}
