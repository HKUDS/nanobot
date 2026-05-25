"""Tests for cache-friendly prompt construction."""

from __future__ import annotations

from datetime import datetime as real_datetime
from pathlib import Path
import datetime as datetime_module

from nanobot.agent.context import ContextBuilder


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


def test_runtime_context_is_preamble_to_user_message(tmp_path) -> None:
    """Runtime metadata is a preamble to the single user message — not a separate turn.

    Keeping it merged preserves user/assistant alternation in the prompt.
    Two consecutive user messages (metadata, then real input) were causing
    models to treat the metadata block as a session boundary and deny
    access to history that was plainly above.
    """
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

    # Exactly one user message at the tail; runtime context is its preamble.
    assert messages[-1]["role"] == "user"
    content = messages[-1]["content"]
    assert isinstance(content, str)
    assert content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG)
    assert "Current Time:" in content
    assert "Channel: cli" in content
    assert "Chat ID: direct" in content
    assert content.endswith("Return exactly: OK")

    # No second user message — no `user → user` adjacency to confuse models.
    user_messages = [m for m in messages if m["role"] == "user"]
    assert len(user_messages) == 1


def test_runtime_context_hints_to_skip_reply_on_fs_channel(tmp_path) -> None:
    """fs (peer-to-peer) inbound should carry a hint discouraging reflexive replies."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    messages = builder.build_messages(
        history=[],
        current_message="hi from peer",
        channel="fs",
        chat_id="Iroh",
    )
    content = messages[-1]["content"]
    assert "peer agent" in content
    assert "Reply only" in content


def test_runtime_context_has_no_fs_hint_for_other_channels(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    messages = builder.build_messages(
        history=[],
        current_message="hi",
        channel="telegram",
        chat_id="12345",
    )
    content = messages[-1]["content"]
    assert "peer agent" not in content


def test_runtime_context_preamble_in_multipart_content(tmp_path) -> None:
    """When the user sends media, the runtime context is the first text part."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    # Force list-content path by passing media that exists (use a stub file).
    img = tmp_path / "img.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)  # not a real png, just non-empty bytes
    messages = builder.build_messages(
        history=[],
        current_message="describe this",
        media=[str(img)],
        channel="telegram",
        chat_id="42",
    )

    content = messages[-1]["content"]
    assert isinstance(content, list)
    # Runtime context is the first part; user text is later.
    assert content[0]["type"] == "text"
    assert content[0]["text"].startswith(ContextBuilder._RUNTIME_CONTEXT_TAG)
