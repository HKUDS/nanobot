"""Tests for staging attachment paths into the media bucket for session replay."""

from pathlib import Path

from nanobot.config.loader import set_config_path
from nanobot.config.paths import get_media_dir
from nanobot.utils.session_attachments import stage_media_paths_for_session_replay


def test_persist_media_stages_workspace_file(tmp_path: Path) -> None:
    set_config_path(tmp_path / "config.json")
    outside = tmp_path / "workspace" / "report.md"
    outside.parent.mkdir(parents=True)
    outside.write_text("body", encoding="utf-8")

    out = stage_media_paths_for_session_replay([str(outside)])

    assert len(out) == 1
    staged = Path(out[0])
    assert staged.is_file()
    assert staged.read_text(encoding="utf-8") == "body"
    assert staged.resolve().is_relative_to(get_media_dir().resolve())


def test_persist_media_keeps_files_already_under_media_root(tmp_path: Path) -> None:
    set_config_path(tmp_path / "config.json")
    media = get_media_dir("websocket")
    media.mkdir(parents=True, exist_ok=True)
    inside = media / "keep-me.txt"
    inside.write_text("x", encoding="utf-8")

    out = stage_media_paths_for_session_replay([str(inside.resolve())])

    assert out == [str(inside.resolve())]
