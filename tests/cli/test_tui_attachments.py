from pathlib import Path

from nanobot.cli.tui.attachments import extract_audio, extract_media


def _make_image(tmp_path: Path, name: str = "shot.png") -> Path:
    path = tmp_path / name
    path.write_bytes(b"\x89PNG\r\n")
    return path


def test_plain_text_is_untouched(tmp_path: Path) -> None:
    text, media = extract_media("just a normal sentence")
    assert text == "just a normal sentence"
    assert media == []


def test_extracts_existing_image_path(tmp_path: Path) -> None:
    image = _make_image(tmp_path)
    text, media = extract_media(f"what is in {image}")
    assert media == [str(image.resolve())]
    assert text == "what is in"


def test_image_only_message_leaves_empty_text(tmp_path: Path) -> None:
    image = _make_image(tmp_path)
    text, media = extract_media(str(image))
    assert media == [str(image.resolve())]
    assert text == ""


def test_nonexistent_image_path_is_kept_as_text(tmp_path: Path) -> None:
    missing = tmp_path / "nope.png"
    text, media = extract_media(f"describe {missing}")
    assert media == []
    assert text == f"describe {missing}"


def test_non_image_file_is_not_attached(tmp_path: Path) -> None:
    doc = tmp_path / "notes.txt"
    doc.write_text("hi")
    text, media = extract_media(f"read {doc}")
    assert media == []
    assert text == f"read {doc}"


def test_quoted_path_with_spaces(tmp_path: Path) -> None:
    image = _make_image(tmp_path, "my shot.png")
    text, media = extract_media(f'look at "{image}" please')
    assert media == [str(image.resolve())]
    assert text == "look at please"


def test_apostrophe_falls_back_to_plain_text(tmp_path: Path) -> None:
    # Unbalanced quote (shlex would raise) → treated as plain text, no crash.
    text, media = extract_media("what's this")
    assert media == []
    assert text == "what's this"


def test_extract_audio_finds_audio_path(tmp_path: Path) -> None:
    audio = tmp_path / "note.mp3"
    audio.write_bytes(b"ID3")
    text, paths = extract_audio(f"transcribe {audio}")
    assert paths == [str(audio.resolve())]
    assert text == "transcribe"


def test_extract_audio_ignores_images(tmp_path: Path) -> None:
    image = tmp_path / "pic.png"
    image.write_bytes(b"\x89PNG")
    text, paths = extract_audio(f"look {image}")
    assert paths == []
    assert text == f"look {image}"
    # ...while extract_media ignores audio.
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    text2, media = extract_media(f"hear {audio}")
    assert media == []
    assert text2 == f"hear {audio}"
