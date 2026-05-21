from pathlib import Path

from nanobot.agent.context import ContextBuilder
from nanobot.config.schema import InputLimitsConfig
from nanobot.utils.helpers import detect_audio_mime, video_mime_compat

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x04\x00\x01"
    b"\x0b\x0e-\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"


def _builder(tmp_path: Path, input_limits: InputLimitsConfig | None = None) -> ContextBuilder:
    return ContextBuilder(tmp_path, input_limits=input_limits)


class TestAudioDetection:
    def test_detect_wav_from_magic_bytes(self) -> None:
        assert detect_audio_mime(WAV_BYTES) == "audio/wav"

    def test_detect_mp3_from_magic_bytes(self) -> None:
        mp3 = b"\xff\xfb\x90\x00"
        assert detect_audio_mime(mp3) == "audio/mpeg"

    def test_detect_fallback_to_filename(self) -> None:
        assert detect_audio_mime(b"unknown", filename="song.mp3") == "audio/mpeg"

    def test_returns_none_for_non_audio(self) -> None:
        assert detect_audio_mime(PNG_BYTES) is None


class TestVideoMimeCompat:
    def test_mp4_is_compatible(self) -> None:
        assert video_mime_compat("video/mp4") is True

    def test_unknown_is_not_compatible(self) -> None:
        assert video_mime_compat("video/avi") is False

    def test_none_is_not_compatible(self) -> None:
        assert video_mime_compat(None) is False


class TestBuildUserContentMultimodal:
    def test_audio_block_when_supported(self, tmp_path: Path) -> None:
        builder = _builder(tmp_path)
        path = tmp_path / "voice.wav"
        path.write_bytes(WAV_BYTES)

        content = builder._build_user_content("transcribe", [str(path)], supports_audio=True)

        assert isinstance(content, list)
        audio_blocks = [b for b in content if b.get("type") == "input_audio"]
        assert len(audio_blocks) == 1
        assert audio_blocks[0]["input_audio"]["format"] == "wav"

    def test_audio_placeholder_when_not_supported(self, tmp_path: Path) -> None:
        builder = _builder(tmp_path)
        path = tmp_path / "voice.wav"
        path.write_bytes(WAV_BYTES)

        content = builder._build_user_content("transcribe", [str(path)], supports_audio=False)

        assert isinstance(content, list)
        assert any("[audio:" in b.get("text", "") for b in content)

    def test_video_block_when_supported(self, tmp_path: Path) -> None:
        builder = _builder(tmp_path)
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"\x00" * 64)

        content = builder._build_user_content("describe", [str(path)], supports_video=True)

        assert isinstance(content, list)
        video_blocks = [b for b in content if b.get("type") == "video_url"]
        assert len(video_blocks) == 1
        assert video_blocks[0]["video_url"]["url"].startswith("data:video/mp4;base64,")

    def test_video_placeholder_when_not_supported(self, tmp_path: Path) -> None:
        builder = _builder(tmp_path)
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"\x00" * 64)

        content = builder._build_user_content("describe", [str(path)], supports_video=False)

        assert isinstance(content, list)
        assert any("[video:" in b.get("text", "") for b in content)

    def test_vision_fallback_downgrades_image(self, tmp_path: Path) -> None:
        builder = _builder(tmp_path)
        path = tmp_path / "pic.png"
        path.write_bytes(PNG_BYTES)

        content = builder._build_user_content("look", [str(path)], supports_vision=False)

        assert isinstance(content, list)
        assert any("[image:" in b.get("text", "") for b in content)
        assert not any(b.get("type") == "image_url" for b in content)

    def test_image_limit_count(self, tmp_path: Path) -> None:
        builder = _builder(tmp_path)
        paths = []
        for i in range(5):
            path = tmp_path / f"img{i}.png"
            path.write_bytes(PNG_BYTES)
            paths.append(str(path))

        content = builder._build_user_content("describe", paths)

        assert isinstance(content, list)
        image_count = sum(1 for b in content if b.get("type") == "image_url")
        assert image_count == 3  # default max_input_images
        assert any("only the first 3 images" in b.get("text", "") for b in content)

    def test_image_limit_bytes(self, tmp_path: Path) -> None:
        builder = _builder(tmp_path)
        big = tmp_path / "big.png"
        big.write_bytes(PNG_BYTES + b"x" * builder.input_limits.max_input_image_bytes)

        content = builder._build_user_content("analyze", [str(big)])

        assert isinstance(content, str)
        assert "file too large" in content

    def test_audio_limit_count(self, tmp_path: Path) -> None:
        limits = InputLimitsConfig(max_input_audios=1)
        builder = _builder(tmp_path, input_limits=limits)
        for i in range(2):
            path = tmp_path / f"snd{i}.wav"
            path.write_bytes(WAV_BYTES)

        content = builder._build_user_content(
            "compare", [str(tmp_path / "snd0.wav"), str(tmp_path / "snd1.wav")], supports_audio=True
        )

        assert isinstance(content, list)
        audio_count = sum(1 for b in content if b.get("type") == "input_audio")
        assert audio_count == 1
        assert any("only 1 audio" in b.get("text", "") for b in content)

    def test_audio_limit_bytes(self, tmp_path: Path) -> None:
        limits = InputLimitsConfig(max_input_audio_bytes=32)
        builder = _builder(tmp_path, input_limits=limits)
        path = tmp_path / "big.wav"
        path.write_bytes(WAV_BYTES + b"x" * 64)

        content = builder._build_user_content("analyze", [str(path)], supports_audio=True)

        assert isinstance(content, str)
        assert "file too large" in content

    def test_mixed_media_types(self, tmp_path: Path) -> None:
        builder = _builder(tmp_path)
        img = tmp_path / "pic.png"
        img.write_bytes(PNG_BYTES)
        snd = tmp_path / "voice.wav"
        snd.write_bytes(WAV_BYTES)
        vid = tmp_path / "clip.mp4"
        vid.write_bytes(b"\x00" * 64)

        content = builder._build_user_content(
            "analyze",
            [str(img), str(snd), str(vid)],
            supports_vision=True,
            supports_audio=True,
            supports_video=True,
        )

        assert isinstance(content, list)
        assert any(b.get("type") == "image_url" for b in content)
        assert any(b.get("type") == "input_audio" for b in content)
        assert any(b.get("type") == "video_url" for b in content)
