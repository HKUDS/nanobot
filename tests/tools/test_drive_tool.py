"""Tests for Google Drive tool (shared-folder service account model)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.drive import (
    DriveToolConfig,
    GoogleDriveTool,
    _DriveClient,
)
from nanobot.config.schema import Config, ToolsConfig


def _fake_service(meta_by_id: dict[str, dict[str, Any]]) -> Any:
    service = MagicMock()

    def _get(**kwargs: Any) -> MagicMock:
        file_id = str(kwargs["fileId"])
        request = MagicMock()
        request.execute.return_value = meta_by_id[file_id]
        return request

    service.files.return_value.get = _get
    return service


def test_drive_client_allows_descendants_of_configured_root() -> None:
    meta = {
        "root": {"id": "root", "parents": [], "trashed": False},
        "child": {"id": "child", "parents": ["root"], "trashed": False},
        "outside": {"id": "outside", "parents": ["other"], "trashed": False},
        "other": {"id": "other", "parents": [], "trashed": False},
    }
    client = _DriveClient(_fake_service(meta), frozenset({"root"}))
    assert client.is_allowed("root")
    assert client.is_allowed("child")
    assert not client.is_allowed("outside")


def test_drive_client_rejects_trashed_files() -> None:
    meta = {
        "root": {"id": "root", "parents": [], "trashed": False},
        "gone": {"id": "gone", "parents": ["root"], "trashed": True},
    }
    client = _DriveClient(_fake_service(meta), frozenset({"root"}))
    assert not client.is_allowed("gone")


def test_drive_search_keeps_paging_until_it_finds_allowed_results() -> None:
    meta = {
        "outside": {"id": "outside", "parents": ["other"], "trashed": False},
        "other": {"id": "other", "parents": [], "trashed": False},
        "inside": {"id": "inside", "parents": ["root"], "trashed": False},
    }
    service = _fake_service(meta)
    first = MagicMock()
    first.execute.return_value = {
        "files": [{"id": "outside", "name": "Outside"}],
        "nextPageToken": "next",
    }
    second = MagicMock()
    second.execute.return_value = {
        "files": [{"id": "inside", "name": "Inside"}],
    }
    service.files.return_value.list.side_effect = [first, second]
    client = _DriveClient(service, frozenset({"root"}))

    assert client.search("name contains 'report'", page_size=1) == [{
        "id": "inside",
        "name": "Inside",
        "mimeType": None,
        "modifiedTime": None,
        "size": None,
    }]
    assert service.files.return_value.list.call_count == 2


def test_drive_download_rejects_files_over_the_configured_limit() -> None:
    service = _fake_service({
        "large": {
            "id": "large",
            "name": "large.zip",
            "mimeType": "application/zip",
            "parents": ["root"],
            "trashed": False,
            "size": "11",
        },
    })
    client = _DriveClient(service, frozenset({"root"}))

    with pytest.raises(ValueError, match="download limit"):
        client.download_bytes("large", max_bytes=10)
    service.files.return_value.get_media.assert_not_called()


def test_google_drive_tool_enabled_requires_roots_and_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creds = tmp_path / "sa.json"
    creds.write_text(
        '{"type":"service_account","client_email":"bot@example.com","private_key":"key"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "nanobot.agent.tools.drive._require_google_deps",
        lambda: (MagicMock(), MagicMock(), MagicMock(), MagicMock()),
    )
    cfg = Config(
        tools=ToolsConfig(
            drive=DriveToolConfig(
                enabled=True,
                credentials_path=str(creds),
                root_folder_ids=["folder123"],
            )
        )
    )
    ctx = ToolContext(config=cfg.tools, workspace=str(tmp_path))
    assert GoogleDriveTool.enabled(ctx)

    cfg_disabled = Config(
        tools=ToolsConfig(
            drive=DriveToolConfig(enabled=False, credentials_path=str(creds), root_folder_ids=["x"]),
        )
    )
    assert not GoogleDriveTool.enabled(ToolContext(config=cfg_disabled.tools, workspace=str(tmp_path)))

    creds.write_text("{}", encoding="utf-8")
    assert not GoogleDriveTool.enabled(ctx)

    creds.write_text(
        '{"type":"service_account","client_email":"bot@example.com","private_key":"key"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "nanobot.agent.tools.drive._require_google_deps",
        MagicMock(side_effect=RuntimeError("missing")),
    )
    assert not GoogleDriveTool.enabled(ctx)


@pytest.mark.asyncio
async def test_google_drive_list_roots(tmp_path: Path) -> None:
    tool = GoogleDriveTool(
        workspace=tmp_path,
        config=DriveToolConfig(root_folder_ids=["root"]),
    )
    client = MagicMock()
    client.list_roots.return_value = [{"id": "root", "name": "Shared"}]
    tool._client = client

    result = await tool.execute(action="list")
    assert '"Shared"' in result
    client.list_roots.assert_called_once()


@pytest.mark.asyncio
async def test_google_drive_download_writes_under_workspace(tmp_path: Path) -> None:
    tool = GoogleDriveTool(
        workspace=tmp_path,
        config=DriveToolConfig(root_folder_ids=["root"], download_subdir="drive"),
    )
    client = MagicMock()
    client.download_bytes.return_value = (b"hello", "notes.txt", "text/plain")
    tool._client = client

    result = await tool.execute(action="download", file_id="file1", path="notes.txt")
    out = tmp_path / "drive" / "notes.txt"
    assert out.read_bytes() == b"hello"
    assert "notes.txt" in result


@pytest.mark.asyncio
async def test_google_drive_download_uses_drive_name_when_path_is_omitted(
    tmp_path: Path,
) -> None:
    tool = GoogleDriveTool(
        workspace=tmp_path,
        config=DriveToolConfig(root_folder_ids=["root"], download_subdir="drive"),
    )
    client = MagicMock()
    client.download_bytes.return_value = (b"hello", "meeting notes.txt", "text/plain")
    tool._client = client

    result = await tool.execute(action="download", file_id="file1")

    assert (tmp_path / "drive" / "meeting notes.txt").read_bytes() == b"hello"
    assert "meeting notes.txt" in result


@pytest.mark.asyncio
async def test_google_drive_download_cannot_escape_workspace(tmp_path: Path) -> None:
    tool = GoogleDriveTool(
        workspace=tmp_path,
        config=DriveToolConfig(root_folder_ids=["root"], download_subdir="drive"),
    )
    client = MagicMock()
    client.download_bytes.return_value = (b"hello", "notes.txt", "text/plain")
    tool._client = client

    result = await tool.execute(
        action="download",
        file_id="file1",
        path="../../outside.txt",
    )

    assert "outside allowed directory" in result
    assert not (tmp_path.parent / "outside.txt").exists()


@pytest.mark.asyncio
async def test_execute_surfaces_missing_dependency_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = GoogleDriveTool(
        workspace=tmp_path,
        config=DriveToolConfig(root_folder_ids=["root"]),
    )

    def _missing() -> tuple[Any, Any]:
        raise RuntimeError("Run: nanobot plugins enable drive")

    monkeypatch.setattr("nanobot.agent.tools.drive._require_google_deps", _missing)
    result = await tool.execute(action="list", folder_id="root")
    assert "plugins enable drive" in result
