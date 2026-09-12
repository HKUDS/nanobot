"""Regression tests for QQ inbound attachment download SSRF protection."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

pytest.importorskip("botpy")


def _make_channel():
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.qq.runtime import QQChannel, QQConfig

    bus = MessageBus()
    config = QQConfig(app_id="test_app", secret="test_secret", allow_from=["*"])
    return QQChannel(config, bus)


class _FakeDownloadResp:
    def __init__(self, status: int = 200, body: bytes = b"", content_type: str = "") -> None:
        self.status = status
        self.headers: dict[str, str] = {"Content-Type": content_type} if content_type else {}
        self.content = _FakeDownloadContent(body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeDownloadContent:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def iter_chunked(self, _chunk_size: int) -> AsyncIterator[bytes]:
        if self._body:
            yield self._body


class _FakeDownloadHttp:
    """Records get() calls; never performs real I/O."""

    def __init__(self, status: int = 200, body: bytes = b"", content_type: str = "") -> None:
        self.get_calls: list[tuple[str, dict[str, object]]] = []
        self._status = status
        self._body = body
        self._content_type = content_type

    def get(self, url: str, **kwargs: object) -> _FakeDownloadResp:
        self.get_calls.append((url, kwargs))
        return _FakeDownloadResp(self._status, self._body, self._content_type)


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://127.0.0.1/attachment",
    "http://10.0.0.1/attachment",
    "http://[::1]/attachment",
    "//127.0.0.1/attachment",
])
async def test_inbound_download_blocks_ssrf_target(url: str) -> None:
    """An inbound attachment URL resolving to an internal target is never fetched.

    Mirrors the outbound _read_media_bytes guard and the napcat/dingtalk
    inbound download protection.
    """
    channel = _make_channel()
    fake_http = _FakeDownloadHttp()
    channel._http = fake_http

    result = await channel._download_to_media_dir_chunked(
        url, filename_hint="x.bin"
    )

    assert result is None
    assert fake_http.get_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
async def test_inbound_download_does_not_follow_redirects(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    """A redirect on an inbound attachment download must be rejected, not followed."""
    monkeypatch.setattr("nanobot.channels.qq.runtime.validate_url_target", lambda _url: (True, ""))
    channel = _make_channel()
    fake_http = _FakeDownloadHttp(status=status)
    channel._http = fake_http

    result = await channel._download_to_media_dir_chunked(
        "https://example.com/attachment.bin", filename_hint="x.bin"
    )

    assert result is None
    assert len(fake_http.get_calls) == 1
    assert fake_http.get_calls[0][1]["allow_redirects"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://example.com/attachment",
    "//example.com/attachment",
])
async def test_inbound_download_saves_successful_attachment(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    """A valid 200 response still follows the normal atomic media write path."""
    validated_urls: list[str] = []

    def validate(target: str) -> tuple[bool, str]:
        validated_urls.append(target)
        return True, ""

    monkeypatch.setattr("nanobot.channels.qq.runtime.validate_url_target", validate)
    channel = _make_channel()
    channel._media_root = tmp_path
    fake_http = _FakeDownloadHttp(body=b"qq attachment", content_type="application/pdf")
    channel._http = fake_http

    result = await channel._download_to_media_dir_chunked(
        url, filename_hint="report"
    )

    assert result is not None
    saved_path = tmp_path / "report.pdf"
    assert result == str(saved_path)
    assert saved_path.read_bytes() == b"qq attachment"
    assert validated_urls == ["https://example.com/attachment"]
    assert fake_http.get_calls[0][0] == validated_urls[0]
    assert fake_http.get_calls[0][1]["allow_redirects"] is False
