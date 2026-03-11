from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.feishu import (
    FeishuChannel,
    _extract_element_content,
    _extract_interactive_content,
    _extract_post_content,
    _extract_post_text,
    _extract_share_card_content,
)
from nanobot.channels.retry import ChannelHealth


def _channel() -> FeishuChannel:
    ch = object.__new__(FeishuChannel)
    ch._client = None
    ch._running = False
    ch._loop = None
    ch._processed_message_ids = {}
    ch._ws_client = None
    ch.bus = SimpleNamespace(publish_inbound=AsyncMock())
    ch.config = SimpleNamespace()
    ch._health = ChannelHealth()
    return ch


def test_extract_helpers_cover_multiple_tags() -> None:
    assert "shared chat" in _extract_share_card_content({"chat_id": "c1"}, "share_chat")
    assert "shared user" in _extract_share_card_content({"user_id": "u1"}, "share_user")
    assert "system" in _extract_share_card_content({}, "system")
    assert _extract_share_card_content({}, "unknown") == "[unknown]"

    content = {
        "title": {"content": "T"},
        "elements": [
            {"tag": "markdown", "content": "md"},
            {"tag": "div", "text": {"content": "divtext"}},
            {"tag": "a", "href": "https://x", "text": "linktext"},
            {"tag": "button", "text": {"content": "btn"}, "url": "https://b"},
            {"tag": "img", "alt": {"content": "pic"}},
            {"tag": "plain_text", "content": "plain"},
        ],
    }
    extracted = _extract_interactive_content(content)
    joined = "\n".join(extracted)
    assert "title: T" in joined
    assert "md" in joined
    assert "divtext" in joined
    assert "link: https://x" in joined
    assert "btn" in joined
    assert "pic" in joined
    assert "plain" in joined

    assert _extract_interactive_content('{"title": "X"}') == ["title: X"]
    assert _extract_interactive_content("") == []
    assert _extract_element_content({"tag": "note", "elements": [{"tag": "plain_text", "content": "n"}]}) == ["n"]


def test_extract_post_content_variants() -> None:
    direct = {
        "title": "Hello",
        "content": [[{"tag": "text", "text": "A"}, {"tag": "img", "image_key": "img1"}]],
    }
    text, images = _extract_post_content(direct)
    assert text == "Hello A"
    assert images == ["img1"]
    assert _extract_post_text(direct) == "Hello A"

    localized = {
        "zh_cn": {
            "title": "CN",
            "content": [[{"tag": "at", "user_name": "alice"}, {"tag": "a", "text": "url"}]],
        }
    }
    l_text, l_images = _extract_post_content(localized)
    assert "CN" in l_text and "@alice" in l_text
    assert l_images == []


def test_markdown_card_helpers() -> None:
    ch = _channel()
    table = "|A|B|\n|---|---|\n|1|2|\n"
    parsed = ch._parse_md_table(table)
    assert parsed is not None and parsed["tag"] == "table"

    content = "# Heading\nBody\n\n" + table
    elements = ch._build_card_elements(content)
    assert any(e.get("tag") == "table" for e in elements)
    assert any(e.get("tag") in ("div", "markdown") for e in elements)

    split = ch._split_headings("## H2\ntext\n```py\nprint(1)\n```")
    assert any(e.get("tag") == "div" for e in split)


@pytest.mark.asyncio
async def test_download_and_save_media_and_send_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ch = _channel()
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    ch._download_image_sync = lambda *_a: (b"img", "a.jpg")  # type: ignore[method-assign]
    path, text = await ch._download_and_save_media("image", {"image_key": "k"}, "m1")
    assert path is not None and path.endswith("a.jpg")
    assert "image" in text

    ch._download_file_sync = lambda *_a: (b"aud", None)  # type: ignore[method-assign]
    path2, text2 = await ch._download_and_save_media("audio", {"file_key": "k2"}, "m2")
    assert path2 is not None
    assert "audio" in text2

    ch._client = None
    await ch.send(OutboundMessage(channel="feishu", chat_id="oc_1", content="hello"))

    sent: list[tuple[str, str, str, str]] = []
    ch._client = object()
    ch._upload_image_sync = lambda _p: "imgk"  # type: ignore[method-assign]
    ch._upload_file_sync = lambda _p: "filek"  # type: ignore[method-assign]
    ch._send_message_sync = lambda ridt, rid, mt, c: sent.append((ridt, rid, mt, c)) or True  # type: ignore[method-assign]

    media_img = tmp_path / "x.jpg"
    media_img.write_bytes(b"1")
    media_file = tmp_path / "x.pdf"
    media_file.write_bytes(b"2")

    await ch.send(
        OutboundMessage(
            channel="feishu",
            chat_id="oc_2",
            content="Hello\n|A|\n|---|\n|1|",
            media=[str(media_img), str(media_file), str(tmp_path / "missing.bin")],
        )
    )
    assert any(item[2] == "interactive" for item in sent)
    assert any(item[2] == "image" for item in sent)
    assert any(item[2] == "file" for item in sent)


@pytest.mark.asyncio
async def test_on_message_paths() -> None:
    ch = _channel()
    ch._processed_message_ids = {}
    ch._add_reaction = AsyncMock()
    ch._download_and_save_media = AsyncMock(return_value=("/tmp/a.jpg", "[image: a.jpg]"))
    ch._handle_message = AsyncMock()

    event = SimpleNamespace(
        message=SimpleNamespace(
            message_id="m1",
            chat_id="chat1",
            chat_type="group",
            message_type="post",
            content=json.dumps(
                {
                    "title": "T",
                    "content": [[{"tag": "img", "image_key": "k1"}, {"tag": "text", "text": "body"}]],
                }
            ),
        ),
        sender=SimpleNamespace(sender_type="user", sender_id=SimpleNamespace(open_id="u1")),
    )
    await ch._on_message(SimpleNamespace(event=event))
    assert ch._handle_message.await_count == 1

    await ch._on_message(SimpleNamespace(event=event))
    assert ch._handle_message.await_count == 1

    bot_event = SimpleNamespace(
        message=SimpleNamespace(
            message_id="m2",
            chat_id="chat1",
            chat_type="p2p",
            message_type="text",
            content=json.dumps({"text": "hello"}),
        ),
        sender=SimpleNamespace(sender_type="bot", sender_id=SimpleNamespace(open_id="u1")),
    )
    await ch._on_message(SimpleNamespace(event=bot_event))
    assert ch._handle_message.await_count == 1
