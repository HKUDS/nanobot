from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.attachment_store import AttachmentStore
from nanobot.webui.background import save_background
from nanobot.webui.inbound_commands import WebUICommandRouter
from nanobot.webui.ws_http import GatewayHTTPHandler


def image_bytes(fmt="PNG"):
    out = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(out, fmt)
    return out.getvalue()


async def test_background_auth_and_staged_upload(tmp_path):
    store = AttachmentStore(tmp_path / "staging")
    body = image_bytes("JPEG")

    async def chunks():
        yield body

    reference = await store.upload(chunks(), owner="alice", mime="image/jpeg", size=len(body))
    handler = GatewayHTTPHandler.__new__(GatewayHTTPHandler)
    handler.bus = MessageBus()
    handler.settings = SimpleNamespace(config=SimpleNamespace(path=tmp_path / "config.json"))
    handler.tokens = SimpleNamespace(check_api_token=lambda request: request.headers.get("Authorization") == "Bearer valid")
    router = WebUICommandRouter.__new__(WebUICommandRouter)
    router._http_router = handler
    router._uploads = SimpleNamespace(store=store, owner=lambda connection: connection)
    router.request_locks = {}
    path = "/api/settings/background"
    request = Request(path, Headers())
    assert (await handler._dispatch_resolved(None, request, path)).status_code == 401
    request.headers["Authorization"] = "Bearer valid"
    assert (await handler._dispatch_resolved(None, request, path)).status_code == 404
    assert (await router.execute_webui_request("bob", "background.update", {"reference": reference})).status == 400
    assert (await router.execute_webui_request("alice", "background.update", {"reference": reference})).result == {"ok": True}
    result = await handler._dispatch_resolved(None, request, path)
    assert result.status_code == 200
    assert result.headers["Content-Type"] == "image/png"
    assert result.headers["Cache-Control"] == "no-store"
    assert bytes(result.body).startswith(b"\x89PNG")
    assert (await router.execute_webui_request("alice", "background.update", {"reference": reference})).status == 400
    assert (await router.execute_webui_request("alice", "background.delete", {})).result == {"ok": True}
    assert (await handler._dispatch_resolved(None, request, path)).status_code == 404


def test_reject_unsafe_images_without_replacing_existing(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(image_bytes())
    directory = tmp_path / "webui"
    save_background(directory, source, "image/png")
    existing = (directory / "background.png").read_bytes()
    source.write_bytes(b"<svg onload='alert(1)'/>")
    with pytest.raises(ValueError):
        save_background(directory, source, "image/png")
    source.write_bytes(image_bytes("JPEG"))
    with pytest.raises(ValueError):
        save_background(directory, source, "image/png")
    assert (directory / "background.png").read_bytes() == existing


async def test_background_style_persistence_and_validation(tmp_path):
    handler = GatewayHTTPHandler.__new__(GatewayHTTPHandler)
    handler.bus = MessageBus()
    handler.settings = SimpleNamespace(config=SimpleNamespace(path=tmp_path / "config.json"))
    handler.tokens = SimpleNamespace(check_api_token=lambda request: request.headers.get("Authorization") == "Bearer valid")
    router = WebUICommandRouter.__new__(WebUICommandRouter)
    router._http_router = handler
    router.request_locks = {}
    path = "/api/settings/background-style"
    request = Request(path, Headers())
    assert (await handler._dispatch_resolved(None, request, path)).status_code == 401
    request.headers["Authorization"] = "Bearer valid"

    async def get_style():
        response = await handler._dispatch_resolved(None, request, path)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        return json.loads(response.body)

    assert await get_style() == {"blur": 5, "veil": 88}
    style_file = tmp_path / "webui" / "background-style"
    style_file.parent.mkdir()
    for legacy, expected in (("plugin.v2-soft", 5), ('{"filter":"old","blur":13}', 13),
                             ('{"filter":"old"}', 5), ('{"blur":0}', 0)):
        style_file.write_text(legacy, encoding="ascii")
        assert await get_style() == {"blur": expected, "veil": 88}
    for blur, veil in ((0, 0), (20, 100), (7, 42)):
        assert (await router.execute_webui_request(
            "alice", "background.style", {"blur": blur, "veil": veil}
        )).result == {"ok": True}
        assert await get_style() == {"blur": blur, "veil": veil}
        assert json.loads(style_file.read_text()) == {"blur": blur, "veil": veil}
    saved = style_file.read_bytes()
    for field, invalid_values in (("blur", (None, True, False, -1, 21, 1.0, "5", [], {})),
                                  ("veil", (None, True, False, -1, 101, 1.0, "88", [], {}))):
        for invalid in invalid_values:
            payload = {"blur": 7, "veil": 42, field: invalid}
            assert (await router.execute_webui_request("alice", "background.style", payload)).status == 400
    for payload in ({}, {"blur": 7}, {"veil": 42}):
        assert (await router.execute_webui_request("alice", "background.style", payload)).status == 400
    assert style_file.read_bytes() == saved
    assert (await router.execute_webui_request("alice", "background.delete", {})).result == {"ok": True}
    assert await get_style() == {"blur": 7, "veil": 42}
    for corrupt in (b"a" * 100_000, b"\xff", b'{}', b'{"filter":"x","blur":true}',
                    b'{"filter":"x","blur":21}', b'{"filter":"x","blur":5,"blur":6}'):
        style_file.write_bytes(corrupt)
        assert await get_style() == {"blur": 5, "veil": 88}
    for invalid in (True, False, -1, 101, 1.0, "88"):
        style_file.write_text(json.dumps({"blur": 13, "veil": invalid}))
        assert await get_style() == {"blur": 13, "veil": 88}



def test_background_style_failed_replace_preserves_both_values(tmp_path, monkeypatch):
    from nanobot.webui.background import load_background_style, save_background_style

    save_background_style(tmp_path, 3, 30)

    def fail_replace(*args):
        raise OSError("replacement failed")

    monkeypatch.setattr("nanobot.webui.background.os.replace", fail_replace)
    with pytest.raises(OSError):
        save_background_style(tmp_path, 19, 90)
    assert load_background_style(tmp_path) == {"blur": 3, "veil": 30}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["background-style"]
