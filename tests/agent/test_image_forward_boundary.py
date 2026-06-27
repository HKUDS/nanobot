"""Boundary tests: image-strip fallback vs. forwarding an uploaded file (#4345/#4346)."""

from __future__ import annotations

from pathlib import Path

from nanobot.agent.context import ContextBuilder
from nanobot.agent.tools.message import MessageTool
from nanobot.providers.base import LLMProvider

# Minimal valid 1x1 PNG so _build_user_content recognizes the file as an image.
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000154a24f9b0000000049454e44ae426082"
)


def _make_media(tmp_path: Path) -> Path:
    media_file = tmp_path / "media" / "uploaded.png"
    media_file.parent.mkdir(parents=True, exist_ok=True)
    media_file.write_bytes(PNG_BYTES)
    return media_file


def _build_messages(tmp_path: Path, inbound_text: str, media_file: Path) -> list[dict]:
    builder = ContextBuilder(workspace=tmp_path)
    content = builder._build_user_content(inbound_text, [str(media_file)])
    assert isinstance(content, list)
    return [{"role": "user", "content": content}]


def _text_blocks(messages: list[dict]) -> str:
    return "\n".join(
        b.get("text") or ""
        for m in messages
        for b in (m.get("content") or [])
        if isinstance(b, dict) and b.get("type") == "text"
    )


def test_stripped_image_signals_unviewable_and_leaks_no_path(tmp_path: Path) -> None:
    """The fix: stripped image becomes an unviewable marker with no server path."""
    media_file = _make_media(tmp_path)
    messages = _build_messages(tmp_path, "what is this?", media_file)

    stripped = LLMProvider._strip_image_content(messages)
    assert stripped is not None

    texts = _text_blocks(stripped)
    assert "omitted" in texts and "cannot be viewed" in texts
    assert str(media_file) not in texts
    assert all(
        b.get("type") != "image_url"
        for m in stripped
        for b in (m.get("content") or [])
        if isinstance(b, dict)
    )


def test_full_path_breadcrumb_survives_strip_and_stays_forwardable(tmp_path: Path) -> None:
    """WhatsApp/Telegram (full-path content tag): forwarding still works, no regression."""
    media_file = _make_media(tmp_path)
    messages = _build_messages(tmp_path, f"send this\n[image: {media_file}]", media_file)

    stripped = LLMProvider._strip_image_content(messages)
    assert str(media_file) in _text_blocks(stripped)  # text breadcrumb untouched

    tool = MessageTool(workspace=tmp_path, restrict_to_workspace=False)
    resolved = tool._resolve_media([str(media_file)])
    assert resolved == [str(media_file)]
    assert Path(resolved[0]).is_file()


def test_basename_only_breadcrumb_is_not_forwardable_after_strip(tmp_path: Path) -> None:
    """KNOWN limitation: WeCom (filename-only content tag) loses its same-turn forward
    reference once the image is stripped.

    This pins the current boundary; it does not describe desired end state. The fix is a
    turn-scoped attachment handle (opaque id resolved server-side, no raw path).
    TODO(#4345): when that lands, add a handle-based "forward still works" test and
    update this one — the handle uses a different token, so this assertion will not flip
    on its own.
    """
    media_file = _make_media(tmp_path)
    messages = _build_messages(tmp_path, "send this\n[image: uploaded.png]", media_file)

    stripped = LLMProvider._strip_image_content(messages)
    assert str(media_file) not in _text_blocks(stripped)  # leak gone

    tool = MessageTool(workspace=tmp_path, restrict_to_workspace=False)
    resolved = tool._resolve_media(["uploaded.png"])
    assert resolved != [str(media_file)]
    assert not Path(resolved[0]).is_file()
