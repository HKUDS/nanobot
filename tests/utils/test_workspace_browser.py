"""Project selection directory metadata contracts."""

import os
import stat
import sys
from pathlib import Path

import pytest

from nanobot.security.workspace_access import WorkspaceScopeError
from nanobot.webui.workspace_browser import browse_workspace_directories


def test_directory_browser_filters_folders_and_exposes_navigation(tmp_path: Path) -> None:
    (tmp_path / "Beta").mkdir()
    (tmp_path / "alpha").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "secret.txt").write_text("file contents")
    result = browse_workspace_directories(str(tmp_path), default_workspace=tmp_path)
    assert [entry["name"] for entry in result["entries"]] == ["alpha", "Beta"]
    assert result["path"] == str(tmp_path)
    assert result["parent"] == str(tmp_path.parent)
    hidden = browse_workspace_directories(str(tmp_path), default_workspace=tmp_path, show_hidden=True, query="HID")
    assert hidden["entries"] == [{"name": ".hidden", "path": str(tmp_path / ".hidden")}]


@pytest.mark.skipif(sys.platform != "darwin", reason="Finder hidden flags are macOS metadata")
def test_directory_browser_honors_finder_hidden_flag(tmp_path: Path) -> None:
    hidden = tmp_path / "Finder hidden"
    hidden.mkdir()
    os.chflags(hidden, stat.UF_HIDDEN)
    visible = browse_workspace_directories(str(tmp_path), default_workspace=tmp_path)
    assert visible["entries"] == []
    shown = browse_workspace_directories(str(tmp_path), default_workspace=tmp_path, show_hidden=True)
    assert shown["entries"] == [{"name": hidden.name, "path": str(hidden)}]


def test_directory_filter_reaches_folders_beyond_display_limit(tmp_path: Path) -> None:
    for index in range(501):
        (tmp_path / f"project-{index:03}").mkdir()
    result = browse_workspace_directories(str(tmp_path), default_workspace=tmp_path)
    assert len(result["entries"]) == 500
    assert result["truncated"] is True
    filtered = browse_workspace_directories(str(tmp_path), default_workspace=tmp_path, query="500")
    assert filtered["entries"] == [{"name": "project-500", "path": str(tmp_path / "project-500")}]
    assert filtered["truncated"] is False


@pytest.mark.parametrize("path", ["relative/project", "invalid\0path"])
def test_directory_browser_rejects_invalid_user_paths(tmp_path: Path, path: str) -> None:
    with pytest.raises(WorkspaceScopeError):
        browse_workspace_directories(path, default_workspace=tmp_path)


def test_partial_address_lists_matching_parent_folders_and_exact_address_lists_children(tmp_path: Path) -> None:
    for name in ("workspace", "workspace-two", "other"):
        (tmp_path / name).mkdir()
    (tmp_path / "workspace" / "src").mkdir()
    (tmp_path / "worksp-file").write_text("not a folder")
    partial = browse_workspace_directories(str(tmp_path / "worksp"), default_workspace=tmp_path, allow_partial=True)
    assert partial["path"] == str(tmp_path)
    assert partial["partial"] is True
    assert [entry["name"] for entry in partial["entries"]] == ["workspace", "workspace-two"]
    exact = browse_workspace_directories(str(tmp_path / "workspace"), default_workspace=tmp_path, allow_partial=True)
    assert exact["partial"] is False
    assert exact["entries"] == [{"name": "src", "path": str(tmp_path / "workspace" / "src")}]
    missing = browse_workspace_directories(str(tmp_path / "missing"), default_workspace=tmp_path, allow_partial=True)
    assert missing["partial"] is True
    assert missing["entries"] == []
    with pytest.raises(WorkspaceScopeError):
        browse_workspace_directories(str(tmp_path / "worksp"), default_workspace=tmp_path)


def test_partial_address_matches_before_display_limit_and_explicit_hidden_prefix(tmp_path: Path) -> None:
    for index in range(501):
        (tmp_path / f"a-workspace-{index:03}").mkdir()
    (tmp_path / "workspace").mkdir()
    (tmp_path / ".private").mkdir()
    result = browse_workspace_directories(str(tmp_path / "worksp"), default_workspace=tmp_path, allow_partial=True)
    assert result["entries"] == [{"name": "workspace", "path": str(tmp_path / "workspace")}]
    assert result["truncated"] is False
    hidden = browse_workspace_directories(str(tmp_path / ".priv"), default_workspace=tmp_path, allow_partial=True)
    assert hidden["entries"] == [{"name": ".private", "path": str(tmp_path / ".private")}]
