from pathlib import Path

from nanobot.agent.context import ContextBuilder
from nanobot.config.schema import InputLimitsConfig


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x04\x00\x01"
    b"\x0b\x0e-\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _builder(tmp_path: Path, input_limits: InputLimitsConfig | None = None) -> ContextBuilder:
    return ContextBuilder(tmp_path, input_limits=input_limits)


def test_build_user_content_keeps_only_first_three_images(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    max_images = builder.input_limits.max_input_images
    paths = []
    for i in range(max_images + 1):
        path = tmp_path / f"img{i}.png"
        path.write_bytes(PNG_BYTES)
        paths.append(str(path))

    content = builder._build_user_content("describe these", paths)

    assert isinstance(content, list)
    assert sum(1 for block in content if block.get("type") == "image_url") == max_images
    assert content[-1]["text"].startswith(
        f"[Skipped 1 image: only the first {max_images} images are included]"
    )


def test_build_user_content_skips_invalid_images_with_note(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    bad = tmp_path / "not-image.txt"
    bad.write_text("hello", encoding="utf-8")

    content = builder._build_user_content("what is this?", [str(bad)])

    assert isinstance(content, str)
    assert "[Skipped image: unsupported or invalid image format (not-image.txt)]" in content
    assert content.endswith("what is this?")


def test_build_user_content_skips_missing_file(tmp_path: Path) -> None:
    builder = _builder(tmp_path)

    content = builder._build_user_content("hello", [str(tmp_path / "ghost.png")])

    assert isinstance(content, str)
    assert "[Skipped image: file not found (ghost.png)]" in content
    assert content.endswith("hello")


def test_build_user_content_skips_large_images_with_note(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    big = tmp_path / "big.png"
    big.write_bytes(PNG_BYTES + b"x" * builder.input_limits.max_input_image_bytes)

    content = builder._build_user_content("analyze", [str(big)])

    limit_mb = builder.input_limits.max_input_image_bytes // (1024 * 1024)
    assert isinstance(content, str)
    assert f"[Skipped image: file too large (big.png, limit {limit_mb} MB)]" in content


def test_build_user_content_respects_custom_input_limits(tmp_path: Path) -> None:
    builder = _builder(
        tmp_path,
        input_limits=InputLimitsConfig(max_input_images=1, max_input_image_bytes=1024),
    )
    small = tmp_path / "small.png"
    large = tmp_path / "large.png"
    small.write_bytes(PNG_BYTES)
    large.write_bytes(PNG_BYTES + b"x" * 1024)

    content = builder._build_user_content("describe", [str(small), str(large)])

    assert isinstance(content, list)
    assert sum(1 for block in content if block.get("type") == "image_url") == 1
    assert content[-1]["text"].startswith("[Skipped 1 image: only the first 1 images are included]")


def test_build_user_content_keeps_valid_images_and_skip_notes_together(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    good = tmp_path / "good.png"
    bad = tmp_path / "bad.txt"
    good.write_bytes(PNG_BYTES)
    bad.write_text("oops", encoding="utf-8")

    content = builder._build_user_content("check both", [str(good), str(bad)])

    assert isinstance(content, list)
    assert content[0]["type"] == "image_url"
    assert (
        "[Skipped image: unsupported or invalid image format (bad.txt)]"
        in content[-1]["text"]
    )
    assert content[-1]["text"].endswith("check both")
