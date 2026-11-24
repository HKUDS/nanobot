import base64

import pytest
from mcp.types import Implementation

from nanobot.agent.tools.mcp_metadata import server_icons


def _icons(*items):
    return Implementation.model_validate({"name": "demo", "version": "1", "icons": items}).icons


def test_https_icons_keep_only_same_origin_and_standard_fields():
    src = "https://MCP.example:443/assets/logo.svg"
    icons = _icons(
        {"src": src, "mimeType": "image/svg+xml", "theme": "light", "sizes": ["any", "64x64", "large"], "secret": "ignored"},
        {"src": "https://cdn.example/logo.png"},
        {"src": "https://mcp.example:444/logo.png"},
        {"src": "http://mcp.example/logo.png"},
        {"src": "https://user:secret@mcp.example/logo.png"},
        {"src": "https://evil.example\\@mcp.example/logo.png"},
        {"src": "file:///icon.png"},
        {"src": "/logo.png"},
    )
    assert server_icons(icons, remote_url="https://mcp.example/rpc") == [
        {"src": src, "mimeType": "image/svg+xml", "theme": "light", "sizes": ["any", "64x64"]},
    ]
    assert server_icons(icons, remote_url=None) == []


def test_jpg_alias_is_canonical_for_inline_and_remote_images():
    remote = "https://mcp.example/icon.jpg"
    icons = _icons(
        {"src": "data:image/jpg;base64,/9j/4A==", "mimeType": "image/jpeg"},
        {"src": "data:image/jpeg;base64,/9j/4A==", "mimeType": "image/jpg"},
        {"src": remote, "mimeType": "image/jpg"},
    )
    inline = {"src": "data:image/jpeg;base64,/9j/4A==", "mimeType": "image/jpeg"}
    assert server_icons(icons, remote_url="https://mcp.example/rpc") == [
        inline, inline, {"src": remote, "mimeType": "image/jpeg"},
    ]


@pytest.mark.parametrize("remote_url", [None, "https://mcp.example/rpc"])
def test_inline_icons_are_bounded_raster_metadata(remote_url):
    png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+k7uoAAAAASUVORK5CYII="
    huge = base64.b64encode(b"\x89PNG\r\n\x1a\n" + bytes(64 * 1024)).decode()
    icons = _icons(
        {"src": png, "theme": {"untrusted": True}},
        {"src": "data:image/png;base64," + huge},
        {"src": png, "mimeType": "image/jpeg"},
        {"src": "data:image/png;base64,////?"},
        {"src": "data:image/png;base64,PHN2Zy8+"},
        {"src": "data:image/svg+xml;base64,PHN2Zy8+"},
    )
    assert server_icons(icons, remote_url=remote_url) == [{"src": png}]
    assert len(server_icons(_icons(*[{"src": png}] * 32), remote_url=remote_url)) == 8
