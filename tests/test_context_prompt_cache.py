"""Tests for cache-friendly prompt construction."""

from __future__ import annotations

from datetime import datetime as real_datetime
from pathlib import Path
import datetime as datetime_module
from unittest.mock import MagicMock

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.bus.events import InboundAttachment
from nanobot.session.manager import Session


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
    """Runtime metadata should be merged with the user message."""
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

    # Runtime context is now merged with user message into a single message
    assert messages[-1]["role"] == "user"
    user_content = messages[-1]["content"]
    assert isinstance(user_content, str)
    assert ContextBuilder._RUNTIME_CONTEXT_TAG in user_content
    assert "Current Time:" in user_content
    assert "Channel: cli" in user_content
    assert "Chat ID: direct" in user_content
    assert "Return exactly: OK" in user_content


def test_attachment_context_is_separate_from_plain_user_text(tmp_path) -> None:
    """Attachment excerpts should travel in a dedicated context block, not in message text."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    messages = builder.build_messages(
        history=[],
        current_message="Please summarize the attachment.",
        attachments=[
            InboundAttachment(
                kind="document",
                name="notes.pdf",
                local_path="/tmp/notes.pdf",
                source="feishu:file",
                extracted_text="First page text",
                extracted_text_source="pdf:pypdf",
                extracted_text_truncated=True,
            )
        ],
        channel="feishu",
        chat_id="oc_123",
    )

    user_content = messages[-1]["content"]
    assert isinstance(user_content, list)
    assert user_content[0]["type"] == "text"
    assert ContextBuilder._RUNTIME_CONTEXT_TAG in user_content[0]["text"]
    assert user_content[1]["type"] == "text"
    assert ContextBuilder._ATTACHMENT_CONTEXT_TAG in user_content[1]["text"]
    assert "\"name\": \"notes.pdf\"" in user_content[1]["text"]
    assert "\"extracted_text_source\": \"pdf:pypdf\"" in user_content[1]["text"]
    assert "\"extracted_text_truncated\": true" in user_content[1]["text"]
    assert user_content[2] == {"type": "text", "text": "Please summarize the attachment."}


def test_attachment_metadata_dicts_are_supported(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    messages = builder.build_messages(
        history=[],
        current_message="Summarize this file.",
        attachments=[{
            "kind": "document",
            "path": "/tmp/notes.pdf",
            "name": "notes.pdf",
            "mime": "application/pdf",
            "text_excerpt": "First page text",
            "text_status": "extracted",
            "source": "feishu:file",
            "ignored": "value",
        }],
        channel="feishu",
        chat_id="oc_123",
    )

    user_content = messages[-1]["content"]
    assert isinstance(user_content, list)
    assert "\"text_excerpt\": \"First page text\"" in user_content[1]["text"]
    assert "\"text_status\": \"extracted\"" in user_content[1]["text"]
    assert "\"ignored\"" not in user_content[1]["text"]


def test_attachment_diagnostics_are_preserved_in_prompt_context(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    messages = builder.build_messages(
        history=[],
        current_message="Why is the PDF text missing?",
        attachments=[
            InboundAttachment(
                kind="document",
                name="scan.pdf",
                local_path="/tmp/scan.pdf",
                source="feishu:file",
                extraction_note="No readable text could be extracted from this PDF.",
            )
        ],
        channel="feishu",
        chat_id="oc_123",
    )

    user_content = messages[-1]["content"]
    assert isinstance(user_content, list)
    assert "\"extraction_note\": \"No readable text could be extracted from this PDF.\"" in user_content[1]["text"]


def test_attachment_metadata_dicts_preserve_prompt_safe_notes(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    messages = builder.build_messages(
        history=[],
        current_message="Why is text unavailable?",
        attachments=[{
            "kind": "document",
            "path": "/tmp/scan.pdf",
            "name": "scan.pdf",
            "mime": "application/pdf",
            "text_status": "unavailable",
            "text_note": "PDF text extraction unavailable because optional dependency 'pypdf' is not installed.",
            "ignored": "value",
        }],
        channel="feishu",
        chat_id="oc_123",
    )

    user_content = messages[-1]["content"]
    assert isinstance(user_content, list)
    assert "\"text_note\": \"PDF text extraction unavailable because optional dependency 'pypdf' is not installed.\"" in user_content[1]["text"]
    assert "\"ignored\"" not in user_content[1]["text"]


def test_current_prompt_attachments_prefers_first_class_attachments() -> None:
    msg = type("Msg", (), {
        "attachments": [
            InboundAttachment(
                kind="document",
                name="preferred.pdf",
                local_path="/tmp/preferred.pdf",
                source="feishu:file",
            )
        ],
        "metadata": {
            "attachments": [{"name": "fallback.pdf", "kind": "document"}],
        },
    })()

    attachments = AgentLoop._current_prompt_attachments(msg)

    assert attachments == msg.attachments


def test_attachment_context_is_not_persisted_into_session_history(tmp_path) -> None:
    """Runtime and attachment metadata blocks should not be saved as conversation text."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=workspace, model="test-model")
    session = Session(key="feishu:oc_123")

    user_message = builder.build_messages(
        history=[],
        current_message="Please summarize the attachment.",
        attachments=[
            InboundAttachment(
                kind="document",
                name="notes.pdf",
                local_path="/tmp/notes.pdf",
                source="feishu:file",
                extracted_text="First page text",
                extracted_text_source="pdf:pypdf",
                extracted_text_truncated=True,
            )
        ],
        channel="feishu",
        chat_id="oc_123",
    )[-1]

    loop._save_turn(session, [user_message], skip=0)

    assert session.messages == [
        {
            "role": "user",
            "content": "Please summarize the attachment.",
            "timestamp": session.messages[0]["timestamp"],
        }
    ]
