"""Slice C3 — WS channel media uploads + tool-results route per-user."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from nanobot.auth.context import UserContext, current_user_ctx
from nanobot.auth.ids import new_ulid


@pytest.fixture()
def isolate_data_dir(monkeypatch, tmp_path: Path) -> Path:
    config_file = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)
    return tmp_path


@pytest.fixture()
def restore_ctx():
    token = current_user_ctx.set(None)
    yield
    current_user_ctx.reset(token)


def _png_data_url() -> str:
    # 1x1 transparent PNG.
    raw = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _build_channel(isolate_data_dir: Path):
    """Construct a minimal WebSocketChannel for unit-level access."""
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.websocket import WebSocketChannel, WebSocketConfig

    cfg = WebSocketConfig(host="127.0.0.1", port=18800, websocket_requires_token=False)
    bus = MessageBus()
    return WebSocketChannel(cfg, bus)


def test_envelope_media_writes_under_user_dir(
    isolate_data_dir: Path, restore_ctx
) -> None:
    channel = _build_channel(isolate_data_dir)
    ctx = UserContext(user_id=new_ulid())
    paths, reason = channel._save_envelope_media(
        [{"data_url": _png_data_url(), "name": "shot.png"}], user_ctx=ctx
    )
    assert reason is None, reason
    assert len(paths) == 1
    saved = Path(paths[0])
    assert saved.is_file()
    user_media = ctx.media_dir("websocket")
    assert saved.parent == user_media


def test_envelope_media_without_ctx_uses_global_dir(
    isolate_data_dir: Path, restore_ctx
) -> None:
    from nanobot.config.paths import get_media_dir

    channel = _build_channel(isolate_data_dir)
    paths, reason = channel._save_envelope_media(
        [{"data_url": _png_data_url(), "name": "shot.png"}]
    )
    assert reason is None
    saved = Path(paths[0])
    assert saved.parent == get_media_dir("websocket")


def test_envelope_media_two_users_disjoint(
    isolate_data_dir: Path, restore_ctx
) -> None:
    channel = _build_channel(isolate_data_dir)
    alice = UserContext(user_id=new_ulid())
    bob = UserContext(user_id=new_ulid())
    a_paths, _ = channel._save_envelope_media(
        [{"data_url": _png_data_url(), "name": "a.png"}], user_ctx=alice
    )
    b_paths, _ = channel._save_envelope_media(
        [{"data_url": _png_data_url(), "name": "b.png"}], user_ctx=bob
    )
    a = Path(a_paths[0])
    b = Path(b_paths[0])
    assert a.parent != b.parent
    assert alice.user_id in str(a)
    assert bob.user_id in str(b)
    assert alice.user_id not in str(b)
    assert bob.user_id not in str(a)
