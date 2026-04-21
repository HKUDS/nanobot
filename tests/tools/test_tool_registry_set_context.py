"""Regression tests for ToolRegistry.set_context — MIT-138.

Covers the sender-id propagation path from the registry into the filesystem
tools module, which previously referenced a symbol (`_current_sender_id`)
that was not defined in `filesystem.py`.
"""

from __future__ import annotations

from nanobot.agent.tools import filesystem as _fs
from nanobot.agent.tools.registry import ToolRegistry


def test_set_context_does_not_raise() -> None:
    """set_context must complete cleanly — no AttributeError from the
    `_fs._current_sender_id = sender_id` assignment."""
    registry = ToolRegistry()
    # No exception should surface here.
    registry.set_context(session_id="sess-1", channel="slack", sender_id="user-42")


def test_set_context_propagates_sender_to_filesystem_module() -> None:
    """After set_context, the filesystem module's sender-id mirror must match
    the value the registry was given."""
    registry = ToolRegistry()
    registry.set_context(session_id="sess-2", channel="matrix", sender_id="alice")

    assert _fs._current_sender_id == "alice"

    # Subsequent calls overwrite, not append.
    registry.set_context(session_id="sess-3", channel="matrix", sender_id="bob")
    assert _fs._current_sender_id == "bob"


def test_set_context_stores_fields_on_registry() -> None:
    """set_context must persist the full triple on the registry too, so
    per-call audit logging can fall back to them when no override is given."""
    registry = ToolRegistry()
    registry.set_context(session_id="sess-4", channel="teams", sender_id="carol")

    assert registry._session_id == "sess-4"
    assert registry._channel == "teams"
    assert registry._sender_id == "carol"


def test_set_context_default_sender_id_is_empty_string() -> None:
    """sender_id is optional — calling set_context without it must not raise
    and must normalise to an empty string in the filesystem module (matches
    the module-level default)."""
    registry = ToolRegistry()
    registry.set_context(session_id="sess-5", channel="cli")

    assert registry._sender_id == ""
    assert _fs._current_sender_id == ""


def test_filesystem_module_defines_current_sender_id_at_import() -> None:
    """Guard the module-level attribute itself — importing the filesystem
    module without first calling set_context must still leave the symbol
    defined with its documented default value type."""
    # Fresh import shouldn't be needed — we just assert the symbol exists
    # and is a string.  The default value after set_context above may be
    # anything (test ordering is not guaranteed), but the type must hold.
    assert hasattr(_fs, "_current_sender_id")
    assert isinstance(_fs._current_sender_id, str)
