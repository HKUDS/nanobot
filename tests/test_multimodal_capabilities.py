"""Tests for multimodal model capabilities: vision/audio config, media routing, fallback."""

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.config.schema import AgentDefaults, InputLimitsConfig
from nanobot.providers.base import LLMProvider
from nanobot.utils.helpers import audio_mime_compat, detect_audio_mime

# ── Config: supports_vision / supports_audio ──────────────────────────

class TestSupportsVision:
    def test_unconfigured_returns_none(self):
        d = AgentDefaults()
        assert d.supports_vision("gpt-4o") is None

    def test_match_simple(self):
        d = AgentDefaults(vision_models=["gpt-4o", "claude-sonnet-4"])
        assert d.supports_vision("gpt-4o") is True

    def test_match_with_provider_prefix(self):
        d = AgentDefaults(vision_models=["gpt-4o"])
        assert d.supports_vision("openai/gpt-4o-2024-11-20") is True

    def test_no_match(self):
        d = AgentDefaults(vision_models=["gpt-4o"])
        assert d.supports_vision("deepseek-r1") is False

    def test_case_insensitive(self):
        d = AgentDefaults(vision_models=["GPT-4o"])
        assert d.supports_vision("openai/GPT-4O-2024") is True


class TestSupportsAudio:
    def test_unconfigured_returns_none(self):
        d = AgentDefaults()
        assert d.supports_audio("gpt-4o") is None

    def test_match(self):
        d = AgentDefaults(audio_models=["gpt-4o", "gemini-2.0"])
        assert d.supports_audio("google/gemini-2.0-flash") is True

    def test_no_match(self):
        d = AgentDefaults(audio_models=["gpt-4o"])
        assert d.supports_audio("deepseek-r1") is False


class TestSupportsVideo:
    def test_unconfigured_returns_none(self):
        d = AgentDefaults()
        assert d.supports_video("glm-5v-turbo") is None

    def test_match(self):
        d = AgentDefaults(video_models=["glm-5v", "gemini-2.0"])
        assert d.supports_video("zhipu/glm-5v-turbo") is True

    def test_no_match(self):
        d = AgentDefaults(video_models=["glm-5v-turbo"])
        assert d.supports_video("deepseek-r1") is False


# ── detect_audio_mime ─────────────────────────────────────────────────

class TestDetectAudioMime:
    def test_wav(self):
        data = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 8
        assert detect_audio_mime(data) == "audio/wav"

    def test_mp3(self):
        data = b"\xff\xfb" + b"\x00" * 10
        assert detect_audio_mime(data) == "audio/mpeg"

    def test_flac(self):
        data = b"fLaC" + b"\x00" * 10
        assert detect_audio_mime(data) == "audio/flac"

    def test_ogg(self):
        data = b"OggS" + b"\x00" * 10
        assert detect_audio_mime(data) == "audio/ogg"

    def test_m4a(self):
        data = b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 10
        # data[8:12] must be exactly "M4A " (4 bytes including trailing space)
        assert data[4:8] == b"ftyp"
        assert detect_audio_mime(data) == "audio/x-m4a"

    def test_fallback_to_filename(self):
        data = b"\x00" * 20
        assert detect_audio_mime(data, filename="test.mp3") == "audio/mpeg"

    def test_fallback_to_filename_aac(self):
        """AAC with unrecognized magic bytes should fallback to filename."""
        data = b"\x00" * 20
        result = detect_audio_mime(data, filename="test.aac")
        assert result is not None and result.startswith("audio/")

    def test_unknown_returns_none(self):
        data = b"\x00" * 20
        assert detect_audio_mime(data) is None


class TestAudioMimeCompat:
    def test_compatible(self):
        assert audio_mime_compat("audio/wav") is True
        assert audio_mime_compat("audio/mpeg") is True
        assert audio_mime_compat("audio/ogg") is True

    def test_incompatible(self):
        assert audio_mime_compat("audio/silk") is False
        assert audio_mime_compat("audio/amr") is False

    def test_none(self):
        assert audio_mime_compat(None) is False


# ── _build_user_content ───────────────────────────────────────────────

class TestBuildUserContent:
    @pytest.fixture
    def ctx(self, tmp_path):
        return ContextBuilder(tmp_path, timezone="UTC")

    def _make_png(self, size: int = 64) -> bytes:
        """Minimal valid PNG."""
        import struct
        import zlib
        header = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
        ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
        raw = b"\x00\x00\x00\x00"
        idat_crc = zlib.crc32(b"IDAT" + raw) & 0xFFFFFFFF
        idat = struct.pack(">I", len(raw)) + b"IDAT" + raw + struct.pack(">I", idat_crc)
        iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
        iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
        return header + ihdr + idat + iend

    def _make_wav(self) -> bytes:
        """Minimal valid WAV."""
        data = b"\x00\x00"
        fmt_chunk = (
            b"\x01\x00"  # PCM
            + (1).to_bytes(2, "little")  # mono
            + (44100).to_bytes(4, "little")  # sample rate
            + (88200).to_bytes(4, "little")  # byte rate
            + (2).to_bytes(2, "little")  # block align
            + (16).to_bytes(2, "little")  # bits per sample
        )
        return (
            b"RIFF"
            + (36 + len(data)).to_bytes(4, "little")
            + b"WAVE"
            + b"fmt "
            + (16).to_bytes(4, "little")
            + fmt_chunk
            + b"data"
            + len(data).to_bytes(4, "little")
            + data
        )

    def test_no_media_returns_text(self, ctx):
        result = ctx._build_user_content("hello", None)
        assert result == "hello"

    def test_image_sends_image(self, ctx, tmp_path):
        img_path = tmp_path / "test.png"
        img_path.write_bytes(self._make_png())
        result = ctx._build_user_content("look", [str(img_path)], supports_vision=True)
        assert isinstance(result, list)
        assert any(b.get("type") == "image_url" for b in result)

    def test_image_vision_none_sends_image(self, ctx, tmp_path):
        """Unconfigured (None) should preserve existing behavior: send image."""
        img_path = tmp_path / "test.png"
        img_path.write_bytes(self._make_png())
        result = ctx._build_user_content("look", [str(img_path)], supports_vision=None)
        assert isinstance(result, list)
        assert any(b.get("type") == "image_url" for b in result)

    def test_audio_supports_true_compatible_sends_input_audio(self, ctx, tmp_path):
        wav_path = tmp_path / "test.wav"
        wav_path.write_bytes(self._make_wav())
        result = ctx._build_user_content("listen", [str(wav_path)], supports_audio=True)
        assert isinstance(result, list)
        audio_blocks = [b for b in result if b.get("type") == "input_audio"]
        assert len(audio_blocks) == 1
        assert "data" in audio_blocks[0]["input_audio"]

    def test_audio_supports_false_skips(self, ctx, tmp_path):
        wav_path = tmp_path / "test.wav"
        wav_path.write_bytes(self._make_wav())
        result = ctx._build_user_content("listen", [str(wav_path)], supports_audio=False)
        # Audio not supported — audio placeholder instead of input_audio block
        assert isinstance(result, list)
        assert not any(b.get("type") == "input_audio" for b in result)
        assert any("[audio:" in (b.get("text") or "") for b in result)

    def test_audio_supports_none_skips(self, ctx, tmp_path):
        wav_path = tmp_path / "test.wav"
        wav_path.write_bytes(self._make_wav())
        result = ctx._build_user_content("listen", [str(wav_path)], supports_audio=None)
        # Audio support unknown — audio placeholder instead of input_audio block
        assert isinstance(result, list)
        assert not any(b.get("type") == "input_audio" for b in result)

    def test_audio_incompatible_format_skips(self, ctx, tmp_path):
        """SILK format should be skipped even if supports_audio=True."""
        silk_path = tmp_path / "test.silk"
        silk_path.write_bytes(b"\x02#!SILK_V3" + b"\x00" * 20)
        result = ctx._build_user_content("listen", [str(silk_path)], supports_audio=True)
        # SILK is not detected as a known audio format, so it falls through
        # to the generic [file: ...] placeholder
        assert isinstance(result, list)
        assert not any(b.get("type") == "input_audio" for b in result)

    def test_mixed_image_and_audio(self, ctx, tmp_path):
        """Both image and audio in same message with both capabilities enabled."""
        img_path = tmp_path / "test.png"
        img_path.write_bytes(self._make_png())
        wav_path = tmp_path / "test.wav"
        wav_path.write_bytes(self._make_wav())
        result = ctx._build_user_content("check", [str(img_path), str(wav_path)],
                                         supports_vision=True, supports_audio=True)
        assert isinstance(result, list)
        types = [b.get("type") for b in result if isinstance(b, dict)]
        assert "image_url" in types
        assert "input_audio" in types
        assert "text" in types

    def _make_mp4(self) -> bytes:
        """Minimal MP4 with ftyp box (isom brand)."""
        # ftyp box: size(4) + 'ftyp'(4) + brand(4) + ...
        ftyp_data = b"isom" + b"\x00" * 12  # minor_version + compatible brands
        ftyp_box = (8 + len(ftyp_data)).to_bytes(4, "big") + b"ftyp" + ftyp_data
        return ftyp_box

    def test_video_supports_true_sends_video_url(self, ctx, tmp_path):
        mp4_path = tmp_path / "test.mp4"
        mp4_path.write_bytes(self._make_mp4())
        result = ctx._build_user_content("watch", [str(mp4_path)], supports_video=True)
        assert isinstance(result, list)
        video_blocks = [b for b in result if b.get("type") == "video_url"]
        assert len(video_blocks) == 1
        url = video_blocks[0]["video_url"]["url"]
        assert url.startswith("data:video/mp4;base64,")

    def test_video_supports_false_placeholder(self, ctx, tmp_path):
        mp4_path = tmp_path / "test.mp4"
        mp4_path.write_bytes(self._make_mp4())
        result = ctx._build_user_content("watch", [str(mp4_path)], supports_video=False)
        assert isinstance(result, list)
        video_blocks = [b for b in result if b.get("type") == "text" and "[video:" in b.get("text", "")]
        assert len(video_blocks) == 1

    def test_video_supports_none_placeholder(self, ctx, tmp_path):
        """Unconfigured (None) should use [video: path] placeholder."""
        mp4_path = tmp_path / "test.mp4"
        mp4_path.write_bytes(self._make_mp4())
        result = ctx._build_user_content("watch", [str(mp4_path)], supports_video=None)
        assert isinstance(result, list)
        video_blocks = [b for b in result if b.get("type") == "text" and "[video:" in b.get("text", "")]
        assert len(video_blocks) == 1


# ── Audio/Video input limits ──────────────────────────────────────────

class TestInputLimitsAudioVideo:
    @pytest.fixture
    def ctx(self, tmp_path):
        return ContextBuilder(tmp_path, timezone="UTC",
                              input_limits=InputLimitsConfig(
                                  max_input_images=3,
                                  max_input_image_bytes=10 * 1024 * 1024,
                                  max_input_audio_bytes=100,  # 100 bytes for testing
                                  max_input_video_bytes=200,  # 200 bytes for testing
                              ))

    def _make_wav(self) -> bytes:
        """Minimal valid WAV (~50 bytes)."""
        data = b"\x00\x00"
        fmt_chunk = (
            b"\x01\x00" + (1).to_bytes(2, "little") + (44100).to_bytes(4, "little")
            + (88200).to_bytes(4, "little") + (2).to_bytes(2, "little")
            + (16).to_bytes(2, "little")
        )
        return (
            b"RIFF" + (36 + len(data)).to_bytes(4, "little") + b"WAVE"
            + b"fmt " + (16).to_bytes(4, "little") + fmt_chunk
            + b"data" + len(data).to_bytes(4, "little") + data
        )

    def _make_mp4(self) -> bytes:
        """Minimal MP4 with ftyp box."""
        ftyp_data = b"isom" + b"\x00" * 12
        return (8 + len(ftyp_data)).to_bytes(4, "big") + b"ftyp" + ftyp_data

    def test_oversized_audio_skipped_with_note(self, ctx, tmp_path):
        """Audio exceeding max_input_audio_bytes should be skipped with note."""
        wav_path = tmp_path / "big.wav"
        wav_path.write_bytes(self._make_wav() + b"\x00" * 100)  # ~150 bytes > 100 limit
        result = ctx._build_user_content("listen", [str(wav_path)], supports_audio=True)
        assert isinstance(result, str)
        assert "[Skipped audio: file too large" in result
        assert result.endswith("listen")

    def test_audio_within_limit_accepted(self, ctx, tmp_path):
        """Audio within limit should be sent as input_audio."""
        wav_path = tmp_path / "small.wav"
        wav_path.write_bytes(self._make_wav())  # ~50 bytes < 100 limit
        result = ctx._build_user_content("listen", [str(wav_path)], supports_audio=True)
        assert isinstance(result, list)
        assert any(b.get("type") == "input_audio" for b in result)

    def test_oversized_video_skipped_with_note(self, ctx, tmp_path):
        """Video exceeding max_input_video_bytes should be skipped with note."""
        mp4_path = tmp_path / "big.mp4"
        mp4_path.write_bytes(self._make_mp4() + b"\x00" * 200)  # > 200 limit
        result = ctx._build_user_content("watch", [str(mp4_path)], supports_video=True)
        assert isinstance(result, str)
        assert "[Skipped video: file too large" in result

    def test_video_within_limit_accepted(self, ctx, tmp_path):
        """Video within limit should be sent as video_url."""
        mp4_path = tmp_path / "small.mp4"
        mp4_path.write_bytes(self._make_mp4())  # ~24 bytes < 200 limit
        result = ctx._build_user_content("watch", [str(mp4_path)], supports_video=True)
        assert isinstance(result, list)
        assert any(b.get("type") == "video_url" for b in result)

    def test_audio_filename_fallback_mp3(self, ctx, tmp_path):
        """MP3 file with unrecognized magic bytes should fallback to filename."""
        mp3_path = tmp_path / "test.mp3"
        mp3_path.write_bytes(b"\x00" * 50)  # unrecognized magic, but .mp3 extension
        result = ctx._build_user_content("listen", [str(mp3_path)], supports_audio=True)
        assert isinstance(result, list)
        audio_blocks = [b for b in result if b.get("type") == "input_audio"]
        assert len(audio_blocks) == 1
        assert audio_blocks[0]["input_audio"]["format"] == "mp3"

    def test_missing_file_gracefully_skipped(self, ctx, tmp_path):
        """Missing file should be skipped with a visible note."""
        result = ctx._build_user_content("hello", [str(tmp_path / "ghost.wav")], supports_audio=True)
        assert isinstance(result, str)
        assert "[Skipped file: unable to read" in result


# ── _strip_media_content ──────────────────────────────────────────────

class TestStripMediaContent:
    def test_no_media_returns_none(self):
        msgs = [{"role": "user", "content": "hello"}]
        assert LLMProvider._strip_media_content(msgs) is None

    def test_strips_image_url(self):
        msgs = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"},
             "_meta": {"path": "/img.png"}},
            {"type": "text", "text": "desc"},
        ]}]
        result = LLMProvider._strip_media_content(msgs)
        assert result is not None
        assert result[0]["content"][0] == {"type": "text", "text": "[image: /img.png]"}
        assert result[0]["content"][1] == {"type": "text", "text": "desc"}

    def test_strips_input_audio(self):
        msgs = [{"role": "user", "content": [
            {"type": "input_audio", "input_audio": {"data": "abc", "format": "wav"},
             "_meta": {"path": "/audio.wav"}},
            {"type": "text", "text": "desc"},
        ]}]
        result = LLMProvider._strip_media_content(msgs)
        assert result is not None
        assert result[0]["content"][0] == {"type": "text", "text": "[audio: /audio.wav]"}

    def test_strips_both(self):
        msgs = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"},
             "_meta": {"path": "/img.png"}},
            {"type": "input_audio", "input_audio": {"data": "abc", "format": "wav"},
             "_meta": {"path": "/audio.wav"}},
        ]}]
        result = LLMProvider._strip_media_content(msgs)
        assert result is not None
        assert len(result[0]["content"]) == 2
        assert "[image:" in result[0]["content"][0]["text"]
        assert "[audio:" in result[0]["content"][1]["text"]

    def test_strips_video_url(self):
        msgs = [{"role": "user", "content": [
            {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,abc"},
             "_meta": {"path": "/video.mp4"}},
            {"type": "text", "text": "desc"},
        ]}]
        result = LLMProvider._strip_media_content(msgs)
        assert result is not None
        assert result[0]["content"][0] == {"type": "text", "text": "[video: /video.mp4]"}
        assert result[0]["content"][1] == {"type": "text", "text": "desc"}

    def test_string_content_unchanged(self):
        msgs = [{"role": "user", "content": "plain text"}]
        assert LLMProvider._strip_media_content(msgs) is None


# ── _strip_image_content backward compat ──────────────────────────────

class TestStripImageContentCompat:
    def test_still_works(self):
        msgs = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"},
             "_meta": {"path": "/img.png"}},
        ]}]
        result = LLMProvider._strip_image_content(msgs)
        assert result is not None
        assert "[image: /img.png]" in result[0]["content"][0]["text"]


# ── _sanitize_persisted_blocks for input_audio ────────────────────────

class TestSanitizePersistedBlocks:
    @pytest.fixture
    def loop_mock(self):
        from nanobot.agent.loop import AgentLoop
        loop = object.__new__(AgentLoop)
        return loop

    def test_audio_block_replaced_with_placeholder(self, loop_mock):
        content = [
            {"type": "input_audio", "input_audio": {"data": "abc", "format": "wav"},
             "_meta": {"path": "/audio.wav"}},
            {"type": "text", "text": "hello"},
        ]
        result = loop_mock._sanitize_persisted_blocks(content)
        assert len(result) == 2
        assert result[0] == {"type": "text", "text": "[audio: /audio.wav]"}
        assert result[1] == {"type": "text", "text": "hello"}

    def test_image_block_replaced(self, loop_mock):
        content = [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"},
             "_meta": {"path": "/img.png"}},
        ]
        result = loop_mock._sanitize_persisted_blocks(content)
        assert len(result) == 1
        assert "[image: /img.png]" in result[0]["text"]

    def test_video_block_replaced_with_placeholder(self, loop_mock):
        content = [
            {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,abc"},
             "_meta": {"path": "/video.mp4"}},
            {"type": "text", "text": "hello"},
        ]
        result = loop_mock._sanitize_persisted_blocks(content)
        assert len(result) == 2
        assert result[0] == {"type": "text", "text": "[video: /video.mp4]"}
        assert result[1] == {"type": "text", "text": "hello"}

    def test_non_data_image_unchanged(self, loop_mock):
        """Non-data URI image (already a placeholder) should pass through."""
        content = [
            {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
        ]
        result = loop_mock._sanitize_persisted_blocks(content)
        assert len(result) == 1
        assert result[0]["type"] == "image_url"


# ── Anthropic provider input_audio handling ────────────────────────────

class TestAnthropicAudioConversion:
    def test_input_audio_converted_to_text(self):
        from nanobot.providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider.__new__(AnthropicProvider)
        content = [
            {"type": "input_audio", "input_audio": {"data": "abc", "format": "wav"},
             "_meta": {"path": "/test.wav"}},
            {"type": "text", "text": "listen"},
        ]
        result = provider._convert_user_content(content)
        assert isinstance(result, list)
        assert any("[audio:" in b.get("text", "") for b in result if b.get("type") == "text")


# ── OpenAI Codex provider input_audio handling ─────────────────────────

class TestCodexAudioConversion:
    def test_input_audio_passed_through(self):
        from nanobot.providers.openai_codex_provider import _convert_user_message
        content = [
            {"type": "input_audio", "input_audio": {"data": "abc123", "format": "wav"}},
            {"type": "text", "text": "listen"},
        ]
        result = _convert_user_message(content)
        assert result["role"] == "user"
        audio_items = [i for i in result["content"] if i.get("type") == "input_audio"]
        assert len(audio_items) == 1
        assert audio_items[0]["input_audio"]["data"] == "abc123"

    def test_video_url_converted_to_text_placeholder(self):
        from nanobot.providers.openai_codex_provider import _convert_user_message
        content = [
            {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,abc"},
             "_meta": {"path": "/video.mp4"}},
            {"type": "text", "text": "watch"},
        ]
        result = _convert_user_message(content)
        text_items = [i for i in result["content"] if i.get("type") == "input_text"]
        assert any("[video:" in i.get("text", "") for i in text_items)


# ── New tests for review fixes ──────────────────────────────────────────

class TestSupportsVisionFalse:
    """Tests for supports_vision=False (image downgrade to placeholder)."""

    @pytest.fixture
    def ctx(self, tmp_path):
        return ContextBuilder(tmp_path, timezone="UTC")

    def _make_png(self, size: int = 64) -> bytes:
        import struct, zlib
        header = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
        ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
        raw = b"\x00\x00\x00\x00"
        idat_crc = zlib.crc32(b"IDAT" + raw) & 0xFFFFFFFF
        idat = struct.pack(">I", len(raw)) + b"IDAT" + raw + struct.pack(">I", idat_crc)
        iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
        iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
        return header + ihdr + idat + iend

    def test_vision_false_downgrades_to_placeholder(self, ctx, tmp_path):
        img_path = tmp_path / "test.png"
        img_path.write_bytes(self._make_png())
        result = ctx._build_user_content("look", [str(img_path)], supports_vision=False)
        assert isinstance(result, list)
        assert not any(b.get("type") == "image_url" for b in result)
        assert any("[image:" in (b.get("text") or "") for b in result)

    def test_vision_false_no_file_read(self, ctx, tmp_path):
        """With supports_vision=False, file should not be read (no crash on missing)."""
        missing = tmp_path / "nonexistent.png"
        result = ctx._build_user_content("look", [str(missing)], supports_vision=False)
        assert isinstance(result, list)
        assert any("[image:" in (b.get("text") or "") for b in result)


class TestAudioVideoCountLimits:
    """Tests for max_input_audios / max_input_videos count enforcement."""

    @pytest.fixture
    def ctx(self, tmp_path):
        return ContextBuilder(tmp_path, timezone="UTC",
                              input_limits=InputLimitsConfig(
                                  max_input_audios=1,
                                  max_input_videos=1,
                                  max_input_audio_bytes=10 * 1024 * 1024,
                                  max_input_video_bytes=20 * 1024 * 1024,
                              ))

    def _make_wav(self) -> bytes:
        data = b"\x00\x00"
        fmt_chunk = (
            b"\x01\x00" + (1).to_bytes(2, "little") + (44100).to_bytes(4, "little")
            + (88200).to_bytes(4, "little") + (2).to_bytes(2, "little")
            + (16).to_bytes(2, "little")
        )
        return (
            b"RIFF" + (36 + len(data)).to_bytes(4, "little") + b"WAVE"
            + b"fmt " + (16).to_bytes(4, "little") + fmt_chunk
            + b"data" + len(data).to_bytes(4, "little") + data
        )

    def _make_mp4(self) -> bytes:
        ftyp_data = b"isom" + b"\x00" * 12
        return (8 + len(ftyp_data)).to_bytes(4, "big") + b"ftyp" + ftyp_data

    def test_audio_count_limit_enforced(self, ctx, tmp_path):
        """Only first audio should be accepted; second should be skipped."""
        wav1 = tmp_path / "a1.wav"
        wav1.write_bytes(self._make_wav())
        wav2 = tmp_path / "a2.wav"
        wav2.write_bytes(self._make_wav())
        result = ctx._build_user_content("listen", [str(wav1), str(wav2)], supports_audio=True)
        # Should have note about skip + one audio block
        if isinstance(result, list):
            audio_blocks = [b for b in result if b.get("type") == "input_audio"]
            assert len(audio_blocks) == 1
            text_blocks = [b for b in result if b.get("type") == "text"]
            notes_text = " ".join(b.get("text", "") for b in text_blocks)
            assert "Skipped audio" in notes_text
        else:
            # All skipped, result is string
            assert "Skipped audio" in result

    def test_video_count_limit_enforced(self, ctx, tmp_path):
        """Only first video should be accepted; second should be skipped."""
        mp4_1 = tmp_path / "v1.mp4"
        mp4_1.write_bytes(self._make_mp4())
        mp4_2 = tmp_path / "v2.mp4"
        mp4_2.write_bytes(self._make_mp4())
        result = ctx._build_user_content("watch", [str(mp4_1), str(mp4_2)], supports_video=True)
        if isinstance(result, list):
            video_blocks = [b for b in result if b.get("type") == "video_url"]
            assert len(video_blocks) == 1
            text_blocks = [b for b in result if b.get("type") == "text"]
            notes_text = " ".join(b.get("text", "") for b in text_blocks)
            assert "Skipped video" in notes_text
        else:
            assert "Skipped video" in result


class TestVideoMimeCompat:
    """Tests for video_mime_compat function."""

    def test_compatible_mp4(self):
        from nanobot.utils.helpers import video_mime_compat
        assert video_mime_compat("video/mp4") is True

    def test_compatible_webm(self):
        from nanobot.utils.helpers import video_mime_compat
        assert video_mime_compat("video/webm") is True

    def test_compatible_quicktime(self):
        from nanobot.utils.helpers import video_mime_compat
        assert video_mime_compat("video/quicktime") is True

    def test_incompatible_avi(self):
        from nanobot.utils.helpers import video_mime_compat
        assert video_mime_compat("video/x-msvideo") is False

    def test_none(self):
        from nanobot.utils.helpers import video_mime_compat
        assert video_mime_compat(None) is False


class TestSupportsAudioCaseInsensitive:
    """Case insensitivity for supports_audio / supports_video."""

    def test_audio_case_insensitive(self):
        d = AgentDefaults(audio_models=["GPT-4o"])
        assert d.supports_audio("openai/gpt-4o-audio") is True

    def test_video_case_insensitive(self):
        d = AgentDefaults(video_models=["GLM-5V"])
        assert d.supports_video("zhipu/glm-5v-turbo") is True


class TestNonImageOSErrorNote:
    """Non-image media OSError should produce a visible note."""

    @pytest.fixture
    def ctx(self, tmp_path):
        return ContextBuilder(tmp_path, timezone="UTC")

    def test_missing_audio_produces_note(self, ctx, tmp_path):
        result = ctx._build_user_content(
            "hello", [str(tmp_path / "missing.wav")], supports_audio=True
        )
        assert isinstance(result, str)
        assert "[Skipped file: unable to read" in result

    def test_missing_video_produces_note(self, ctx, tmp_path):
        result = ctx._build_user_content(
            "hello", [str(tmp_path / "missing.mp4")], supports_video=True
        )
        assert isinstance(result, str)
        assert "[Skipped file: unable to read" in result
