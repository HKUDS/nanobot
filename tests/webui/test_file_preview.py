import base64
from pathlib import Path

import pytest

from nanobot.security.workspace_access import default_workspace_scope
from nanobot.webui.file_preview import (
    WebUIFilePreviewError,
    file_preview_availability_payload,
    file_preview_payload,
)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII="
)


@pytest.mark.parametrize(("data", "mime"), [
    (PNG, "image/png"),
    (b"\xff\xd8\xff\xe0\0example", "image/jpeg"),
    (b"GIF89a\0example", "image/gif"),
    (b"RIFF\0\0\0\0WEBPexample", "image/webp"),
])
def test_raster_preview_uses_content_signature(tmp_path: Path, data: bytes, mime: str) -> None:
    # Extension must not determine the rendered MIME type.
    image = tmp_path / "figure.bin"
    image.write_bytes(data)
    scope = default_workspace_scope(tmp_path, restrict_to_workspace=True)
    assert file_preview_availability_payload("figure.bin", scope=scope) == {"available": True}
    result = file_preview_payload("figure.bin", scope=scope)
    assert result["kind"] == "image"
    assert result["mime_type"] == mime
    assert base64.b64decode(result["data_url"].split(",", 1)[1]) == data
    assert result["size"] == len(data)


def test_large_raster_is_rejected_without_truncating(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.file_preview.MAX_IMAGE_PREVIEW_BYTES", 32)
    (tmp_path / "large.png").write_bytes(PNG)
    scope = default_workspace_scope(tmp_path, restrict_to_workspace=True)
    for read in (file_preview_payload, file_preview_availability_payload):
        with pytest.raises(WebUIFilePreviewError) as error:
            read("large.png", scope=scope)
        assert error.value.status == 413


@pytest.mark.parametrize("filename", ["page.html", "drawing.svg", "disguised.png"])
def test_active_content_is_only_source(tmp_path: Path, filename: str) -> None:
    content = "<script>window.example = true</script>"
    (tmp_path / filename).write_text(content)
    result = file_preview_payload(
        filename, scope=default_workspace_scope(tmp_path, restrict_to_workspace=True),
    )
    assert result["kind"] == "text"
    assert result["content"] == content


def test_text_truncation_is_unchanged(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("abcdefghijklm")
    result = file_preview_payload(
        "notes.txt", scope=default_workspace_scope(tmp_path, restrict_to_workspace=True), max_bytes=5,
    )
    assert result["content"] == "abcde"
    assert result["truncated"] is True


def test_raster_symlink_cannot_escape_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    image = tmp_path / "outside.png"
    image.write_bytes(PNG)
    (workspace / "linked.png").symlink_to(image)
    with pytest.raises(WebUIFilePreviewError) as error:
        file_preview_payload(
            "linked.png", scope=default_workspace_scope(workspace, restrict_to_workspace=True),
        )
    assert error.value.status == 403


def test_restricted_preview_allows_media_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    uploaded = media / "upload.txt"
    uploaded.write_text("uploaded", encoding="utf-8")
    monkeypatch.setattr("nanobot.webui.file_preview.get_media_dir", lambda: media)

    scope = default_workspace_scope(workspace, restrict_to_workspace=True)

    payload = file_preview_payload(str(uploaded), scope=scope)

    assert payload["content"] == "uploaded"
    assert Path(payload["path"]) == uploaded.resolve()


def test_restricted_preview_rejects_other_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setattr("nanobot.webui.file_preview.get_media_dir", lambda: media)

    scope = default_workspace_scope(workspace, restrict_to_workspace=True)

    with pytest.raises(WebUIFilePreviewError, match="outside the current workspace") as exc_info:
        file_preview_payload(str(outside), scope=scope)

    assert exc_info.value.status == 403
