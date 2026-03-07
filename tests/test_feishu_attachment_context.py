from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.channels.feishu import FeishuChannel
from nanobot.config.schema import FeishuConfig
from nanobot.utils.document_extractor import DocumentExtractionResult


@pytest.mark.asyncio
async def test_feishu_file_message_uses_first_class_attachments_with_extraction_note(tmp_path, monkeypatch) -> None:
    channel = FeishuChannel(config=FeishuConfig(), bus=SimpleNamespace())
    channel._processed_message_ids.clear()

    media_path = tmp_path / "scan.pdf"
    media_path.write_text("placeholder", encoding="utf-8")

    captured: dict[str, object] = {}

    async def _fake_add_reaction(message_id: str, emoji: str) -> None:
        return None

    async def _fake_download_and_save_media(msg_type: str, content_json: dict, message_id: str) -> tuple[str, str]:
        return str(media_path), f"[attachment: {media_path}]"

    async def _fake_handle_message(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(channel, "_add_reaction", _fake_add_reaction)
    monkeypatch.setattr(channel, "_download_and_save_media", _fake_download_and_save_media)
    monkeypatch.setattr("nanobot.channels.feishu.extract_document", lambda path, max_chars: DocumentExtractionResult(
        note="PDF text extraction unavailable because optional dependency 'pypdf' is not installed."
    ))
    monkeypatch.setattr(channel, "_handle_message", _fake_handle_message)

    data = SimpleNamespace(
        event=SimpleNamespace(
            message=SimpleNamespace(
                message_id="mid-1",
                chat_id="chat-1",
                chat_type="p2p",
                message_type="file",
                content=json.dumps({"file_key": "file-1"}),
            ),
            sender=SimpleNamespace(
                sender_type="user",
                sender_id=SimpleNamespace(open_id="user-1"),
            ),
        )
    )

    await channel._on_message(data)

    attachments = captured["attachments"]
    assert isinstance(attachments, list) and len(attachments) == 1
    attachment = attachments[0]
    assert attachment.kind == "document"
    assert attachment.name == "scan.pdf"
    assert attachment.local_path == str(media_path)
    assert attachment.mime_type == "application/pdf"
    assert attachment.extracted_text is None
    assert attachment.extraction_note == "PDF text extraction unavailable because optional dependency 'pypdf' is not installed."

    metadata = captured["metadata"]
    assert metadata["attachments"][0]["text_status"] == "unavailable"
    assert metadata["attachments"][0]["text_note"] == "PDF text extraction unavailable because optional dependency 'pypdf' is not installed."
