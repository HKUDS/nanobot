"""Tests for the signed ``/api/media/<sig>/<payload>`` route and WebUI replay.

The route is the return path for local media rendered by the WebUI. These tests
cover URL signing and serving end-to-end plus the adversarial edges (bad
signatures, ``..`` traversal, non-existent files, non-image types).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.session.manager import SessionManager
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.media_api import (
    b64url_decode,
    b64url_encode,
    sign_media_path,
)

from .ws_test_client import InProcessHttpChannel
from .ws_test_client import http_get as _http_get

# PNG magic bytes + a couple of sentinel bytes so we can verify byte-for-byte
# round-trip of the served payload. Stays under mimetype + size limits.
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x00\x00\x02\x00\x01"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _ch(
    bus: Any,
    *,
    session_manager: SessionManager | None = None,
    workspace_path: Path | None = None,
    port: int,
) -> WebSocketChannel:
    cfg = {
        "enabled": True,
        "allowFrom": ["*"],
        "host": "127.0.0.1",
        "port": port,
        "path": "/",
        "websocketRequiresToken": False,
    }
    parsed = WebSocketConfig.model_validate(cfg)
    gateway = build_gateway_services(
        config=parsed,
        bus=bus,
        session_manager=session_manager,
        static_dist_path=None,
        workspace_path=workspace_path or Path.cwd(),
        default_restrict_to_workspace=False,
        runtime_model_name=None,
        runtime_surface="browser",
        runtime_capabilities_overrides=None,
    )
    return InProcessHttpChannel(cfg, bus, gateway=gateway)


@pytest.fixture()
def bus() -> MagicMock:
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    return b


def _fake_media_dir(root: Path):
    def inner(channel: str | None = None) -> Path:
        path = root / channel if channel else root
        path.mkdir(parents=True, exist_ok=True)
        return path

    return inner


def _sign_media_path(channel: WebSocketChannel, path: Path) -> str | None:
    return sign_media_path(
        path,
        secret=channel.gateway.media.secret,
        media_dir=channel.gateway.media._media_dir,
    )


# ---------------------------------------------------------------------------
# media_api.sign_media_path: the URL minter
# ---------------------------------------------------------------------------


def test_sign_media_path_rejects_paths_outside_media_root(
    bus: MagicMock, tmp_path: Path
) -> None:
    """Paths that resolve outside ``get_media_dir()`` must not be signed.

    This is the single most important invariant of the whole scheme:
    if the minter ever signed an arbitrary path, the HMAC would legitimise
    it for the fetch handler and we'd hand out a disk-read primitive.
    """
    outside = tmp_path / "secrets" / "cred.txt"
    outside.parent.mkdir()
    outside.write_text("nope")
    media = tmp_path / "media"
    media.mkdir()
    channel = _ch(bus, port=0)
    with patch("nanobot.webui.media_gateway.get_media_dir", return_value=media):
        assert _sign_media_path(channel, outside) is None
        # Traversal via the media root is also rejected — the resolve() step
        # normalises ``..`` out before the relative_to check.
        assert _sign_media_path(channel, media / ".." / "secrets" / "cred.txt") is None


def test_sign_media_path_round_trips_via_hmac(
    bus: MagicMock, tmp_path: Path
) -> None:
    """The signature embeds exactly ``HMAC-SHA256(secret, payload)[:16]``."""
    media = tmp_path / "media"
    media.mkdir()
    (media / "a.png").write_bytes(_PNG_BYTES)
    channel = _ch(bus, port=0)
    with patch("nanobot.webui.media_gateway.get_media_dir", return_value=media):
        url = _sign_media_path(channel, media / "a.png")
    assert url is not None
    assert url.startswith("/api/media/")
    sig, payload = url[len("/api/media/"):].split("/", 1)
    expected = hmac.new(
        channel.gateway.media.secret, payload.encode("ascii"), hashlib.sha256
    ).digest()[:16]
    assert b64url_decode(sig) == expected
    # The payload decodes back to the *relative* path — no absolute-path leaks.
    assert b64url_decode(payload).decode() == "a.png"


def test_local_markdown_image_is_staged_and_rewritten(
    bus: MagicMock,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "demo_arch.png").write_bytes(_PNG_BYTES)
    media = tmp_path / "media"
    channel = _ch(bus, workspace_path=workspace, port=0)

    with patch("nanobot.webui.media_gateway.get_media_dir", side_effect=_fake_media_dir(media)):
        first = channel.gateway.media.rewrite_local_markdown_images(
            "The result:\n![Cloud Architecture Diagram](demo_arch.png)"
        )
        second = channel.gateway.media.rewrite_local_markdown_images(
            "The result:\n![Cloud Architecture Diagram](demo_arch.png)"
        )

    assert "![Cloud Architecture Diagram](/api/media/" in first
    assert second == first
    staged = list((media / "websocket").iterdir())
    assert len(staged) == 1
    assert staged[0].read_bytes() == _PNG_BYTES


def test_modified_local_markdown_image_gets_a_new_immutable_url(
    bus: MagicMock,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "demo_arch.png"
    source.write_bytes(_PNG_BYTES)
    media = tmp_path / "media"
    channel = _ch(bus, workspace_path=workspace, port=0)
    markdown = "![Cloud Architecture Diagram](demo_arch.png)"

    with patch("nanobot.webui.media_gateway.get_media_dir", side_effect=_fake_media_dir(media)):
        first = channel.gateway.media.rewrite_local_markdown_images(markdown)
        source.write_bytes(_PNG_BYTES + b"updated")
        second = channel.gateway.media.rewrite_local_markdown_images(markdown)

    assert second != first
    assert len(list((media / "websocket").iterdir())) == 2


def test_local_markdown_video_is_staged_and_rewritten(
    bus: MagicMock,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    video_bytes = b"fake mp4"
    (workspace / "nanobot-intro.mp4").write_bytes(video_bytes)
    media = tmp_path / "media"
    channel = _ch(bus, workspace_path=workspace, port=0)

    with patch("nanobot.webui.media_gateway.get_media_dir", side_effect=_fake_media_dir(media)):
        rewritten = channel.gateway.media.rewrite_local_markdown_images(
            "The result:\n![nanobot-intro.mp4](nanobot-intro.mp4)"
        )

    assert "![nanobot-intro.mp4](/api/media/" in rewritten
    staged = list((media / "websocket").iterdir())
    assert len(staged) == 1
    assert staged[0].read_bytes() == video_bytes


def test_local_markdown_image_rejects_workspace_escape(
    bus: MagicMock,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(_PNG_BYTES)
    media = tmp_path / "media"
    channel = _ch(bus, workspace_path=workspace, port=0)
    text = "![nope](../outside.png)"

    with patch("nanobot.webui.media_gateway.get_media_dir", side_effect=_fake_media_dir(media)):
        assert channel.gateway.media.rewrite_local_markdown_images(text) == text

    assert not (media / "websocket").exists()


# ---------------------------------------------------------------------------
# /api/media/<sig>/<payload>: the serving handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_media_route_serves_signed_file(
    bus: MagicMock, tmp_path: Path
) -> None:
    """Valid signature + existing file => 200 with correct bytes + MIME."""
    media = tmp_path / "media"
    media.mkdir()
    target = media / "round-trip.png"
    target.write_bytes(_PNG_BYTES)

    channel = _ch(bus, port=29920)
    with patch("nanobot.webui.media_gateway.get_media_dir", return_value=media):
        url_path = _sign_media_path(channel, target)
        assert url_path is not None
        server_task = asyncio.create_task(channel.start())
        try:
            resp = await _http_get(f"http://127.0.0.1:29920{url_path}")
        finally:
            await channel.stop()
            await server_task

    assert resp.status_code == 200
    assert resp.content == _PNG_BYTES
    assert resp.headers["content-type"].startswith("image/png")
    # Immutable cache header lets the browser skip round-trips on replay.
    assert "immutable" in resp.headers.get("cache-control", "")
    # Video players rely on byte ranges; images get the header for consistency.
    assert resp.headers.get("accept-ranges") == "bytes"
    # nosniff keeps the browser from second-guessing our Content-Type.
    assert resp.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.asyncio
async def test_media_route_serves_video_byte_ranges(
    bus: MagicMock, tmp_path: Path
) -> None:
    """MP4 playback needs HTTP Range support for mid-stream reads and seeking."""
    media = tmp_path / "media"
    media.mkdir()
    target = media / "clip.mp4"
    target.write_bytes(b"0123456789")

    channel = _ch(bus, port=29927)
    with patch("nanobot.webui.media_gateway.get_media_dir", return_value=media):
        url_path = _sign_media_path(channel, target)
        assert url_path is not None
        server_task = asyncio.create_task(channel.start())
        try:
            resp = await _http_get(
                f"http://127.0.0.1:29927{url_path}",
                headers={"Range": "bytes=2-5"},
            )
        finally:
            await channel.stop()
            await server_task

    assert resp.status_code == 206
    assert resp.content == b"2345"
    assert resp.headers["content-type"].startswith("video/mp4")
    assert resp.headers.get("accept-ranges") == "bytes"
    assert resp.headers.get("content-range") == "bytes 2-5/10"
    assert resp.headers.get("content-length") == "4"


@pytest.mark.asyncio
async def test_media_route_serves_suffix_video_byte_ranges(
    bus: MagicMock, tmp_path: Path
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    target = media / "clip.mp4"
    target.write_bytes(b"0123456789")

    channel = _ch(bus, port=29928)
    with patch("nanobot.webui.media_gateway.get_media_dir", return_value=media):
        url_path = _sign_media_path(channel, target)
        assert url_path is not None
        server_task = asyncio.create_task(channel.start())
        try:
            resp = await _http_get(
                f"http://127.0.0.1:29928{url_path}",
                headers={"Range": "bytes=-3"},
            )
        finally:
            await channel.stop()
            await server_task

    assert resp.status_code == 206
    assert resp.content == b"789"
    assert resp.headers.get("content-range") == "bytes 7-9/10"


@pytest.mark.asyncio
async def test_media_route_rejects_unsatisfiable_byte_range(
    bus: MagicMock, tmp_path: Path
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    target = media / "clip.mp4"
    target.write_bytes(b"0123456789")

    channel = _ch(bus, port=29929)
    with patch("nanobot.webui.media_gateway.get_media_dir", return_value=media):
        url_path = _sign_media_path(channel, target)
        assert url_path is not None
        server_task = asyncio.create_task(channel.start())
        try:
            resp = await _http_get(
                f"http://127.0.0.1:29929{url_path}",
                headers={"Range": "bytes=100-200"},
            )
        finally:
            await channel.stop()
            await server_task

    assert resp.status_code == 416
    assert resp.headers.get("accept-ranges") == "bytes"
    assert resp.headers.get("content-range") == "bytes */10"


@pytest.mark.asyncio
async def test_media_route_rejects_bad_signature(
    bus: MagicMock, tmp_path: Path
) -> None:
    """A payload re-signed with a different secret must 401.

    Protects against a restart: old URLs baked into a stale tab become
    un-forgeable once ``gateway.media.secret`` regenerates.
    """
    media = tmp_path / "media"
    media.mkdir()
    (media / "f.png").write_bytes(_PNG_BYTES)

    channel = _ch(bus, port=29921)
    with patch("nanobot.webui.media_gateway.get_media_dir", return_value=media):
        good = _sign_media_path(channel, media / "f.png")
        assert good is not None
        _, payload = good[len("/api/media/"):].split("/", 1)
        # Forge a sig with a *different* secret.
        forged_mac = hmac.new(
            b"\x00" * 32, payload.encode("ascii"), hashlib.sha256
        ).digest()[:16]
        forged = f"/api/media/{b64url_encode(forged_mac)}/{payload}"

        server_task = asyncio.create_task(channel.start())
        try:
            resp = await _http_get(f"http://127.0.0.1:29921{forged}")
        finally:
            await channel.stop()
            await server_task
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_media_route_rejects_path_traversal_payload(
    bus: MagicMock, tmp_path: Path
) -> None:
    """Even a validly-signed ``..`` payload must not escape the media root.

    The signer never *emits* such payloads, but an attacker who somehow
    obtained the secret (or the channel was misconfigured) must still be
    stopped by the resolve()+relative_to() guard in the serving path.
    """
    media = tmp_path / "media"
    media.mkdir()
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("classified")

    channel = _ch(bus, port=29922)
    # Hand-craft a traversal payload the legit signer would refuse to mint.
    payload = b64url_encode(b"../secret.txt")
    mac = hmac.new(
        channel.gateway.media.secret, payload.encode("ascii"), hashlib.sha256
    ).digest()[:16]
    url = f"/api/media/{b64url_encode(mac)}/{payload}"

    with patch("nanobot.webui.media_gateway.get_media_dir", return_value=media):
        server_task = asyncio.create_task(channel.start())
        try:
            resp = await _http_get(f"http://127.0.0.1:29922{url}")
        finally:
            await channel.stop()
            await server_task
    assert resp.status_code == 404
    assert b"classified" not in resp.content


@pytest.mark.asyncio
async def test_media_route_404s_missing_file(
    bus: MagicMock, tmp_path: Path
) -> None:
    """A signed URL for a file that no longer exists degrades to 404 so the
    client can fall back to the placeholder tile instead of breaking."""
    media = tmp_path / "media"
    media.mkdir()
    target = media / "gone.png"
    target.write_bytes(_PNG_BYTES)

    channel = _ch(bus, port=29923)
    with patch("nanobot.webui.media_gateway.get_media_dir", return_value=media):
        url_path = _sign_media_path(channel, target)
        assert url_path is not None
        target.unlink()  # the file vanishes between signing and fetching
        server_task = asyncio.create_task(channel.start())
        try:
            resp = await _http_get(f"http://127.0.0.1:29923{url_path}")
        finally:
            await channel.stop()
            await server_task
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_media_route_degrades_non_image_to_octet_stream(
    bus: MagicMock, tmp_path: Path
) -> None:
    """A non-image extension must not be served as its native MIME.

    Defence-in-depth: if media_dir ever contained (say) an HTML file, we
    do not want the browser to render it as HTML via the signed route.
    """
    media = tmp_path / "media"
    media.mkdir()
    (media / "scary.html").write_bytes(b"<script>alert(1)</script>")

    channel = _ch(bus, port=29924)
    with patch("nanobot.webui.media_gateway.get_media_dir", return_value=media):
        payload = b64url_encode(b"scary.html")
        mac = hmac.new(
            channel.gateway.media.secret, payload.encode("ascii"), hashlib.sha256
        ).digest()[:16]
        url = f"/api/media/{b64url_encode(mac)}/{payload}"
        server_task = asyncio.create_task(channel.start())
        try:
            resp = await _http_get(f"http://127.0.0.1:29924{url}")
        finally:
            await channel.stop()
            await server_task
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/octet-stream")
    # nosniff is the actual defence when we downgrade to octet-stream:
    # without it the browser might still sniff the bytes as HTML.
    assert resp.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.asyncio
async def test_media_route_serves_svg_with_strict_csp(
    bus: MagicMock, tmp_path: Path
) -> None:
    """Generated SVG can preview as an image without becoming executable HTML."""
    media = tmp_path / "media"
    media.mkdir()
    target = media / "chart.svg"
    target.write_text("<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>")

    channel = _ch(bus, port=29928)
    with patch("nanobot.webui.media_gateway.get_media_dir", return_value=media):
        url_path = _sign_media_path(channel, target)
        assert url_path is not None
        server_task = asyncio.create_task(channel.start())
        try:
            resp = await _http_get(f"http://127.0.0.1:29928{url_path}")
        finally:
            await channel.stop()
            await server_task

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert "default-src 'none'" in resp.headers.get("content-security-policy", "")
    assert "sandbox" in resp.headers.get("content-security-policy", "")
