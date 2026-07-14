from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from nanobot.webui.attachment_ingress import (
    extract_data_url_mime,
    store_inbound_attachments,
)
from nanobot.webui.ingress_policy import AttachmentIngressLimits


def _data_url(mime: str, payload: bytes) -> str:
    encoded = base64.b64encode(payload).decode()
    return f"data:{mime};base64,{encoded}"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("data:image/png;base64,AAAA", "image/png"),
        ("data:IMAGE/JPEG;charset=utf-8;base64,AAAA", "image/jpeg"),
        ("data:video/webm;codecs=vp9;base64,AAAA", "video/webm"),
        ("data:text/plain;base64,AAAA", "text/plain"),
        ("data:image/svg+xml;base64,AAAA", "image/svg+xml"),
        ("data:image/png,AAAA", None),
        ("data:;base64,AAAA", None),
        ("https://example.invalid/image.png", None),
        ("", None),
        (None, None),
    ],
)
def test_extract_data_url_mime_normalizes_only_base64_data_urls(
    url: Any,
    expected: str | None,
) -> None:
    assert extract_data_url_mime(url) == expected


def test_store_inbound_document_preserves_safe_name(tmp_path: Path) -> None:
    paths, rejection = store_inbound_attachments(
        [
            {
                "data_url": _data_url("text/csv", b"name,value\nnanobot,1"),
                "name": "report.csv",
            },
        ],
        media_dir=tmp_path,
        logger=MagicMock(),
    )

    assert rejection is None
    assert len(paths) == 1
    saved = Path(paths[0])
    assert saved.parent == tmp_path
    assert saved.name.endswith("_report.csv")
    assert saved.read_bytes() == b"name,value\nnanobot,1"


def test_invalid_batch_removes_files_already_persisted(tmp_path: Path) -> None:
    paths, rejection = store_inbound_attachments(
        [
            {"data_url": _data_url("image/png", b"valid-first-item")},
            {"data_url": _data_url("image/svg+xml", b"<svg/>")},
        ],
        media_dir=tmp_path,
        logger=MagicMock(),
    )

    assert paths == []
    assert rejection == "mime"
    assert list(tmp_path.iterdir()) == []


def test_invalid_base64_cannot_create_an_empty_attachment(tmp_path: Path) -> None:
    paths, rejection = store_inbound_attachments(
        [{"data_url": "data:text/plain;base64,@@@@", "name": "empty.txt"}],
        media_dir=tmp_path,
        logger=MagicMock(),
    )

    assert paths == []
    assert rejection == "decode"
    assert list(tmp_path.iterdir()) == []


def test_single_file_limit_is_attachment_policy_not_transport(tmp_path: Path) -> None:
    paths, rejection = store_inbound_attachments(
        [{"data_url": _data_url("text/plain", b"12345"), "name": "large.txt"}],
        media_dir=tmp_path,
        logger=MagicMock(),
        limits=AttachmentIngressLimits(max_file_bytes=4, max_total_bytes=20),
    )

    assert paths == []
    assert rejection == "size"
    assert list(tmp_path.iterdir()) == []


def test_total_attachment_policy_rolls_back_the_batch(tmp_path: Path) -> None:
    paths, rejection = store_inbound_attachments(
        [
            {"data_url": _data_url("text/plain", b"1234"), "name": "one.txt"},
            {"data_url": _data_url("text/plain", b"5678"), "name": "two.txt"},
        ],
        media_dir=tmp_path,
        logger=MagicMock(),
        limits=AttachmentIngressLimits(max_file_bytes=4, max_total_bytes=6),
    )

    assert paths == []
    assert rejection == "total_size"
    assert list(tmp_path.iterdir()) == []
