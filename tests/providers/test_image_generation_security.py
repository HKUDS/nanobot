from __future__ import annotations

import socket

import httpx
import pytest

from nanobot.providers import image_generation
from nanobot.providers.image_generation import ImageGenerationError, _download_image_data_url

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
    b"\x00\x00\x00\x0bIDATx\xdacd\xfc\xff\x1f\x00\x03\x03"
    b"\x02\x00\xef\xbf\xa7\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _resolve_public(host: str, port: int | None, *args, **kwargs):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("93.184.216.34", port or 0),
        )
    ]


@pytest.mark.asyncio
async def test_generated_image_download_blocks_private_target() -> None:
    requested = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested = True
        return httpx.Response(200, content=PNG_BYTES)

    with pytest.raises(ImageGenerationError, match="blocked unsafe generated image URL"):
        await _download_image_data_url(
            "http://127.0.0.1/admin",
            transport=httpx.MockTransport(handler),
        )

    assert requested is False


@pytest.mark.asyncio
async def test_generated_image_download_revalidates_redirects(monkeypatch) -> None:
    original_getaddrinfo = socket.getaddrinfo

    def resolve_test_hosts(host: str, port: int | None, *args, **kwargs):
        if host == "cdn.example":
            return _resolve_public(host, port, *args, **kwargs)
        return original_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr("nanobot.security.network.socket.getaddrinfo", resolve_test_hosts)
    requested: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

    with pytest.raises(ImageGenerationError, match="blocked unsafe generated image URL"):
        await _download_image_data_url(
            "https://cdn.example/image.png",
            transport=httpx.MockTransport(handler),
        )

    assert requested == ["https://cdn.example/image.png"]


@pytest.mark.asyncio
async def test_generated_image_download_returns_valid_data_url(monkeypatch) -> None:
    monkeypatch.setattr(
        "nanobot.security.network.socket.getaddrinfo",
        _resolve_public,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=PNG_BYTES)

    result = await _download_image_data_url(
        "https://cdn.example/image.png",
        transport=httpx.MockTransport(handler),
    )

    assert result.startswith("data:image/png;base64,")


class _OversizedStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"12345"
        yield b"6789"


@pytest.mark.asyncio
async def test_generated_image_download_enforces_streaming_size_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        "nanobot.security.network.socket.getaddrinfo",
        _resolve_public,
    )
    monkeypatch.setattr(image_generation, "_IMAGE_DOWNLOAD_MAX_BYTES", 8)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_OversizedStream())

    with pytest.raises(ImageGenerationError, match="download limit"):
        await _download_image_data_url(
            "https://cdn.example/image.png",
            transport=httpx.MockTransport(handler),
        )
