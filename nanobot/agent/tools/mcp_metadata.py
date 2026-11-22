"""Bounded, display-only metadata from an MCP initialize handshake."""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NotRequired, TypedDict
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from mcp.types import Icon


class MCPIcon(TypedDict):
    src: str
    mimeType: NotRequired[str]
    sizes: NotRequired[list[str]]
    theme: NotRequired[str]


@dataclass(frozen=True)
class MCPRuntimeSnapshot:
    statuses: Mapping[str, str]
    icons: Mapping[str, list[MCPIcon]] = field(default_factory=dict[str, list[MCPIcon]])


_MAX_ICONS = 8
_MAX_ICON_BYTES = 64 * 1024
_MAX_DATA_CHARS = 4 * ((_MAX_ICON_BYTES + 2) // 3)
_RASTER_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_URL_TYPES = _RASTER_TYPES | {"image/svg+xml", "image/x-icon", "image/vnd.microsoft.icon"}
_SIZE = re.compile(r"any|[1-9][0-9]{0,4}x[1-9][0-9]{0,4}")


def _https_origin(url: str) -> tuple[str, int] | None:
    # Avoid browser/urllib parser differences (especially backslashes and stripped controls).
    if not url.isascii() or "\\" in url or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        return None
    try:
        parts = urlsplit(url)
        if (parts.scheme == "https" and parts.hostname and parts.username is None
                and "%" not in parts.netloc):
            return parts.hostname, parts.port if parts.port is not None else 443
    except ValueError:
        pass
    return None


def _image_type(mime: str) -> str:
    kind = mime.lower()
    return "image/jpeg" if kind == "image/jpg" else kind


def _safe_data_icon(src: str, mime: str | None) -> str | None:
    # Never interpret SVG/XML, read local files, or decompress untrusted image data here.
    if len(src) > _MAX_DATA_CHARS + 32:
        return None
    header, sep, encoded = src.partition(",")
    kind = _image_type(header[5:].removesuffix(";base64"))
    if (not sep or not header.endswith(";base64") or kind not in _RASTER_TYPES
            or (mime is not None and kind != mime) or len(encoded) > _MAX_DATA_CHARS):
        return None
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(data) > _MAX_ICON_BYTES:
        return None
    if (
        (kind == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
        or (kind == "image/jpeg" and data.startswith(b"\xff\xd8\xff"))
        or (kind == "image/gif" and data.startswith((b"GIF87a", b"GIF89a")))
        or (kind == "image/webp" and data.startswith(b"RIFF") and data[8:12] == b"WEBP")
    ):
        return f"data:{kind};base64,{encoded}"
    return None


def server_icons(icons: list[Icon] | None, *, remote_url: str | None) -> list[MCPIcon]:
    """Allow inline raster data, or HTTPS images on the configured HTTP transport origin."""
    origin = _https_origin(remote_url) if remote_url else None
    result: list[MCPIcon] = []
    for icon in (icons or [])[:_MAX_ICONS]:
        src = icon.src
        if icon.mimeType and len(icon.mimeType) > 64:
            continue
        mime = _image_type(icon.mimeType) if icon.mimeType else None
        if mime is not None and mime not in _URL_TYPES:
            continue
        if src.startswith("data:"):
            canonical = _safe_data_icon(src, mime)
            if canonical is None:
                continue
            src = canonical
        elif len(src) > 2048 or origin is None or _https_origin(src) != origin:
            continue
        item: MCPIcon = {"src": src}
        if mime:
            item["mimeType"] = mime
        if icon.sizes:
            sizes = [size for size in icon.sizes[:8] if _SIZE.fullmatch(size)]
            if sizes:
                item["sizes"] = sizes
        theme = getattr(icon, "theme", None)
        if theme in ("light", "dark"):
            item["theme"] = theme
        result.append(item)
    return result
