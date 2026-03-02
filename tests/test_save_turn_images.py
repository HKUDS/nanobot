"""Test _save_turn strips base64 images and collapses multimodal content to plain text."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.session.manager import Session


def _make_loop(tmp_path: Path) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(
        bus=bus, provider=provider, workspace=tmp_path, model="test-model", memory_window=50
    )


def _b64_image_block(mime: str = "image/jpeg") -> dict:
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,/9j/4AAQSkZJRgABAQ=="},
    }


def _text_block(text: str) -> dict:
    return {"type": "text", "text": text}


class TestSaveTurnImageStripping:
    """Verify that _save_turn collapses multimodal image content to plain text."""

    def test_image_with_path_marker_collapsed_to_string(self, tmp_path: Path) -> None:
        """Base64 image + [image: /path] marker → plain string in session."""
        loop = _make_loop(tmp_path)
        session = Session(key="test:img")

        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": [
                _b64_image_block(),
                _text_block("[image: /home/.nanobot/media/abc123.jpg]"),
            ]},
            {"role": "assistant", "content": "Nice photo!"},
        ]

        loop._save_turn(session, messages, skip=1)

        user_msg = session.messages[0]
        assert user_msg["role"] == "user"
        # Content must be a plain string, not a list
        assert isinstance(user_msg["content"], str)
        # Should mention that an image was sent
        assert "[user sent an image]" in user_msg["content"]
        # Must NOT contain base64 data
        assert "base64" not in user_msg["content"]
        # Must NOT contain the file path marker
        assert "/home/.nanobot/media" not in user_msg["content"]

    def test_image_with_caption_preserves_caption(self, tmp_path: Path) -> None:
        """Caption text is preserved alongside the image placeholder."""
        loop = _make_loop(tmp_path)
        session = Session(key="test:caption")

        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": [
                _b64_image_block(),
                _text_block("[image: /home/.nanobot/media/abc123.jpg]"),
                _text_block("Check out my cat!"),
            ]},
            {"role": "assistant", "content": "Cute cat!"},
        ]

        loop._save_turn(session, messages, skip=1)

        user_msg = session.messages[0]
        assert isinstance(user_msg["content"], str)
        assert "Check out my cat!" in user_msg["content"]
        assert "[user sent an image]" in user_msg["content"]

    def test_image_only_no_caption(self, tmp_path: Path) -> None:
        """Image with no text at all produces a minimal placeholder."""
        loop = _make_loop(tmp_path)
        session = Session(key="test:notext")

        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": [
                _b64_image_block(),
                _text_block("[image: /tmp/photo.png]"),
            ]},
            {"role": "assistant", "content": "I see a photo."},
        ]

        loop._save_turn(session, messages, skip=1)

        user_msg = session.messages[0]
        assert isinstance(user_msg["content"], str)
        assert user_msg["content"].strip() == "[user sent an image]"

    def test_multiple_images_collapsed(self, tmp_path: Path) -> None:
        """Multiple base64 images in one message are all stripped."""
        loop = _make_loop(tmp_path)
        session = Session(key="test:multi")

        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": [
                _b64_image_block("image/jpeg"),
                _b64_image_block("image/png"),
                _text_block("[image: /tmp/a.jpg]"),
                _text_block("[image: /tmp/b.png]"),
                _text_block("Two photos of my garden"),
            ]},
            {"role": "assistant", "content": "Beautiful garden!"},
        ]

        loop._save_turn(session, messages, skip=1)

        user_msg = session.messages[0]
        assert isinstance(user_msg["content"], str)
        assert "Two photos of my garden" in user_msg["content"]
        assert "[user sent an image]" in user_msg["content"]
        assert "base64" not in user_msg["content"]

    def test_plain_text_message_unchanged(self, tmp_path: Path) -> None:
        """Regular text messages are not affected by image stripping."""
        loop = _make_loop(tmp_path)
        session = Session(key="test:text")

        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I'm good!"},
        ]

        loop._save_turn(session, messages, skip=1)

        user_msg = session.messages[0]
        assert user_msg["content"] == "Hello, how are you?"

    def test_file_marker_also_stripped(self, tmp_path: Path) -> None:
        """[file: /path] markers are stripped alongside [image: /path] markers."""
        loop = _make_loop(tmp_path)
        session = Session(key="test:file")

        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": [
                _b64_image_block(),
                _text_block("[file: /home/.nanobot/media/doc.pdf]"),
            ]},
            {"role": "assistant", "content": "Got it."},
        ]

        loop._save_turn(session, messages, skip=1)

        user_msg = session.messages[0]
        assert isinstance(user_msg["content"], str)
        assert "/home/.nanobot/media/doc.pdf" not in user_msg["content"]

    def test_assistant_message_preserved(self, tmp_path: Path) -> None:
        """Assistant messages are saved unchanged."""
        loop = _make_loop(tmp_path)
        session = Session(key="test:asst")

        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": [
                _b64_image_block(),
                _text_block("[image: /tmp/photo.jpg]"),
            ]},
            {"role": "assistant", "content": "I can see a sunset in your photo."},
        ]

        loop._save_turn(session, messages, skip=1)

        assistant_msg = session.messages[1]
        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["content"] == "I can see a sunset in your photo."

    def test_history_does_not_contain_multimodal_list(self, tmp_path: Path) -> None:
        """After save, get_history returns plain strings, not multimodal lists."""
        loop = _make_loop(tmp_path)
        session = Session(key="test:history")

        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": [
                _b64_image_block(),
                _text_block("[image: /tmp/photo.jpg]"),
                _text_block("What's in this image?"),
            ]},
            {"role": "assistant", "content": "It's a cat."},
        ]

        loop._save_turn(session, messages, skip=1)

        history = session.get_history()
        for msg in history:
            if msg["role"] == "user":
                assert isinstance(msg["content"], str), (
                    f"History should contain plain strings, got {type(msg['content'])}"
                )
