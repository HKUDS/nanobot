"""Tests for the signed ``/api/media/<sig>/<payload>`` route and its replay
integration on ``/api/sessions/<key>/messages``.

The route is the return path for images attached to persisted user turns:
:meth:`WebSocketChannel._sign_media_path` mints URLs during session reads,
and :meth:`WebSocketChannel._handle_media_fetch` serves the bytes back.
These tests cover the two halves end-to-end plus the adversarial edges
(bad signatures, ``..`` traversal, non-existent files, non-image types).
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import hmac
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nanobot.channels.websocket import (
    WebSocketChannel,
    _b64url_decode,
    _b64url_encode,
)
from nanobot.session.manager import Session, SessionManager


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
    port: int,
) -> WebSocketChannel:
    return WebSocketChannel(
        {
            "enabled": True,
            "allowFrom": ["*"],
            "host": "127.0.0.1",
            "port": port,
            "path": "/",
            "websocketRequiresToken": False,
        },
        bus,
        session_manager=session_manager,
    )


@pytest.fixture()
def bus() -> MagicMock:
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    return b


async def _http_get(
    url: str, headers: dict[str, str] | None = None
) -> httpx.Response:
    return await asyncio.to_thread(
        functools.partial(httpx.get, url, headers=headers or {}, timeout=5.0)
    )


# ---------------------------------------------------------------------------
# _sign_media_path: the URL minter
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
    with patch("nanobot.channels.websocket.get_media_dir", return_value=media):
        assert channel._sign_media_path(outside) is None
        # Traversal via the media root is also rejected — the resolve() step
        # normalises ``..`` out before the relative_to check.
        assert channel._sign_media_path(media / ".." / "secrets" / "cred.txt") is None


def test_sign_media_path_round_trips_via_hmac(
    bus: MagicMock, tmp_path: Path
) -> None:
    """The signature embeds exactly ``HMAC-SHA256(secret, payload)[:16]``."""
    media = tmp_path / "media"
    media.mkdir()
    (media / "a.png").write_bytes(_PNG_BYTES)
    channel = _ch(bus, port=0)
    with patch("nanobot.channels.websocket.get_media_dir", return_value=media):
        url = channel._sign_media_path(media / "a.png")
    assert url is not None
    assert url.startswith("/api/media/")
    sig, payload = url[len("/api/media/"):].split("/", 1)
    expected = hmac.new(
        channel._media_secret, payload.encode("ascii"), hashlib.sha256
    ).digest()[:16]
    assert _b64url_decode(sig) == expected
    # The payload decodes back to the *relative* path — no absolute-path leaks.
    assert _b64url_decode(payload).decode() == "a.png"


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
    with patch("nanobot.channels.websocket.get_media_dir", return_value=media):
        url_path = channel._sign_media_path(target)
        assert url_path is not None
        server_task = asyncio.create_task(channel.start())
        await asyncio.sleep(0.3)
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


@pytest.mark.asyncio
async def test_media_route_rejects_bad_signature(
    bus: MagicMock, tmp_path: Path
) -> None:
    """A payload re-signed with a different secret must 401.

    Protects against a restart: old URLs baked into a stale tab become
    un-forgeable once ``_media_secret`` regenerates.
    """
    media = tmp_path / "media"
    media.mkdir()
    (media / "f.png").write_bytes(_PNG_BYTES)

    channel = _ch(bus, port=29921)
    with patch("nanobot.channels.websocket.get_media_dir", return_value=media):
        good = channel._sign_media_path(media / "f.png")
        assert good is not None
        _, payload = good[len("/api/media/"):].split("/", 1)
        # Forge a sig with a *different* secret.
        forged_mac = hmac.new(
            b"\x00" * 32, payload.encode("ascii"), hashlib.sha256
        ).digest()[:16]
        forged = f"/api/media/{_b64url_encode(forged_mac)}/{payload}"

        server_task = asyncio.create_task(channel.start())
        await asyncio.sleep(0.3)
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
    payload = _b64url_encode(b"../secret.txt")
    mac = hmac.new(
        channel._media_secret, payload.encode("ascii"), hashlib.sha256
    ).digest()[:16]
    url = f"/api/media/{_b64url_encode(mac)}/{payload}"

    with patch("nanobot.channels.websocket.get_media_dir", return_value=media):
        server_task = asyncio.create_task(channel.start())
        await asyncio.sleep(0.3)
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
    with patch("nanobot.channels.websocket.get_media_dir", return_value=media):
        url_path = channel._sign_media_path(target)
        assert url_path is not None
        target.unlink()  # the file vanishes between signing and fetching
        server_task = asyncio.create_task(channel.start())
        await asyncio.sleep(0.3)
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
    with patch("nanobot.channels.websocket.get_media_dir", return_value=media):
        payload = _b64url_encode(b"scary.html")
        mac = hmac.new(
            channel._media_secret, payload.encode("ascii"), hashlib.sha256
        ).digest()[:16]
        url = f"/api/media/{_b64url_encode(mac)}/{payload}"
        server_task = asyncio.create_task(channel.start())
        await asyncio.sleep(0.3)
        try:
            resp = await _http_get(f"http://127.0.0.1:29924{url}")
        finally:
            await channel.stop()
            await server_task
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/octet-stream")


# ---------------------------------------------------------------------------
# /api/sessions/<key>/messages: media_urls hydration on session read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_messages_exposes_signed_media_urls(
    bus: MagicMock, tmp_path: Path
) -> None:
    """The read path must map persisted ``media`` paths onto signed URLs
    and strip the raw path — the client never learns the server's layout."""
    media = tmp_path / "media"
    media.mkdir()
    img = media / "u.png"
    img.write_bytes(_PNG_BYTES)

    sm = SessionManager(tmp_path / "ws_state")
    sess = Session(key="websocket:media-hydrate")
    sess.add_message("user", "look at this", media=[str(img)])
    sess.add_message("assistant", "nice")
    sm.save(sess)

    channel = _ch(bus, session_manager=sm, port=29925)
    with patch("nanobot.channels.websocket.get_media_dir", return_value=media):
        server_task = asyncio.create_task(channel.start())
        await asyncio.sleep(0.3)
        try:
            boot = await _http_get("http://127.0.0.1:29925/webui/bootstrap")
            token = boot.json()["token"]
            auth = {"Authorization": f"Bearer {token}"}
            resp = await _http_get(
                "http://127.0.0.1:29925/api/sessions/websocket:media-hydrate/messages",
                headers=auth,
            )
            body = resp.json()
            # The signed URL round-trips end-to-end: fetching it yields the same bytes.
            user_msg = next(m for m in body["messages"] if m["role"] == "user")
            urls = user_msg["media_urls"]
            assert isinstance(urls, list) and len(urls) == 1
            assert urls[0]["name"] == "u.png"
            assert urls[0]["url"].startswith("/api/media/")
            # Raw paths must not leak to the wire.
            assert "media" not in user_msg

            # And the URL actually works.
            fetched = await _http_get(f"http://127.0.0.1:29925{urls[0]['url']}")
            assert fetched.status_code == 200
            assert fetched.content == _PNG_BYTES
        finally:
            await channel.stop()
            await server_task


@pytest.mark.asyncio
async def test_session_messages_skips_vanished_media(
    bus: MagicMock, tmp_path: Path
) -> None:
    """Paths that no longer resolve inside the media root produce no URL —
    the message is still delivered, just without the preview."""
    media = tmp_path / "media"
    media.mkdir()

    sm = SessionManager(tmp_path / "ws_state")
    sess = Session(key="websocket:vanished")
    sess.add_message("user", "missing pic", media=[str(media / "absent.png")])
    sm.save(sess)

    channel = _ch(bus, session_manager=sm, port=29926)
    with patch("nanobot.channels.websocket.get_media_dir", return_value=media):
        server_task = asyncio.create_task(channel.start())
        await asyncio.sleep(0.3)
        try:
            boot = await _http_get("http://127.0.0.1:29926/webui/bootstrap")
            token = boot.json()["token"]
            resp = await _http_get(
                "http://127.0.0.1:29926/api/sessions/websocket:vanished/messages",
                headers={"Authorization": f"Bearer {token}"},
            )
            user_msg = next(m for m in resp.json()["messages"] if m["role"] == "user")
            # absent.png lives inside the media root so it *does* get a signed
            # URL (we don't stat the file at signing time — that would slow
            # the listing). Fetching the URL is where the 404 surfaces.
            urls = user_msg.get("media_urls") or []
            assert len(urls) == 1
            fetched = await _http_get(f"http://127.0.0.1:29926{urls[0]['url']}")
            assert fetched.status_code == 404
            assert "media" not in user_msg
        finally:
            await channel.stop()
            await server_task
