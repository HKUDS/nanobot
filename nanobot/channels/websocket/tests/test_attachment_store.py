"""Binary staging regressions; these do not exercise the gateway HTTP listener."""

import asyncio
import re
from pathlib import Path

import pytest

from nanobot.channels.websocket.attachment_policy import AttachmentIngressLimits
from nanobot.channels.websocket.attachment_store import AttachmentStore, AttachmentUploadError
from nanobot.utils.media_decode import save_base64_data_url


async def chunks(raw: bytes):
    for offset in range(0, len(raw), 65536):
        yield raw[offset:offset + 65536]


async def upload(store, raw=b"attachment", owner="owner", mime="image/png", **kwargs):
    return await store.upload(chunks(raw), owner=owner, mime=mime, size=len(raw), **kwargs)


async def test_binary_larger_than_websocket_limit_preserves_layout(tmp_path):
    raw = b"x" * (1024 * 1024 + 1)
    store = AttachmentStore(tmp_path)
    ref = await upload(store, raw)
    assert len(ref) < 100
    paths = store.resolve([ref], owner="owner")
    assert re.fullmatch(r"[0-9a-f]{12}\.png", Path(paths[0]).name)
    assert Path(paths[0]).read_bytes() == raw
    assert store.resolve([ref], owner="owner") == paths  # a failed send is retryable
    assert store.commit([ref], owner="owner") == paths
    store.clear()
    assert Path(paths[0]).read_bytes() == raw  # cleanup must not delete session media
    with pytest.raises(AttachmentUploadError):
        store.resolve([ref], owner="owner")


@pytest.mark.parametrize("mime,filename,pattern", [
    ("application/pdf", "../../report.pdf", r"[0-9a-f]{12}_.+\.pdf"),
    ("video/webm", "ignored.webm", r"[0-9a-f]{12}\.webm"),
    ("text/markdown", "notes.md", r"[0-9a-f]{12}_notes\.md"),
])
async def test_document_and_video_layout_matches_legacy(tmp_path, mime, filename, pattern):
    store = AttachmentStore(tmp_path)
    ref = await upload(store, mime=mime, filename=filename)
    path = Path(store.resolve([ref], owner="owner")[0])
    assert path.parent == tmp_path
    assert re.fullmatch(pattern, path.name)
    import base64
    legacy = save_base64_data_url(
        f"data:{mime};base64," + base64.b64encode(b"attachment").decode(), tmp_path,
        filename=filename if mime != "video/webm" else None,
    )
    assert legacy is not None
    assert path.name[12:] == Path(legacy).name[12:]


async def test_ownership_invalid_and_duplicate_refs_are_atomic(tmp_path):
    store = AttachmentStore(tmp_path)
    ref = await upload(store)
    for references, owner in [([ref], "other"), ([ref, "unknown"], "owner"),
                              ([ref, ref], "owner"), (["../../file"], "owner")]:
        with pytest.raises(AttachmentUploadError):
            store.commit(references, owner=owner)
    assert len(store.resolve([ref], owner="owner")) == 1


@pytest.mark.parametrize("size,raw", [(4, b"12345"), (6, b"12345")])
async def test_body_length_failure_cleans_file_and_capacity(tmp_path, size, raw):
    store = AttachmentStore(tmp_path, max_pending=1, max_pending_bytes=6)
    with pytest.raises(AttachmentUploadError):
        await store.upload(chunks(raw), owner="owner", mime="image/png", size=size)
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]
    assert await upload(store, b"123456")


async def test_reject_metadata_before_reading_body(tmp_path):
    store = AttachmentStore(tmp_path)

    async def unread():
        pytest.fail("Rejected request body was read")
        yield b""

    for owner, mime, size in [("", "image/png", 1), ("owner", "text/javascript", 1),
                              ("owner", "image/png", 7 * 1024 * 1024),
                              ("owner", "image/png", 0)]:
        with pytest.raises(AttachmentUploadError):
            await store.upload(unread(), owner=owner, mime=mime, size=size)
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


async def test_inflight_capacity_and_cancellation(tmp_path):
    store = AttachmentStore(tmp_path, max_pending_bytes=10)
    entered = asyncio.Event()

    async def slow():
        entered.set()
        await asyncio.Event().wait()
        yield b"123456"

    task = asyncio.create_task(store.upload(slow(), owner="owner", mime="image/png", size=6))
    await entered.wait()
    with pytest.raises(AttachmentUploadError, match="storage is full"):
        await upload(store, b"12345")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]
    assert await upload(store, b"1234567890")


async def test_timeout_cleans_partial_upload(tmp_path):
    store = AttachmentStore(tmp_path, upload_timeout=0.01)

    async def slow():
        yield b"1"
        await asyncio.Event().wait()

    with pytest.raises(TimeoutError):
        await store.upload(slow(), owner="owner", mime="image/png", size=2)
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


async def test_progressing_upload_can_outlast_idle_timeout(tmp_path):
    store = AttachmentStore(tmp_path, upload_timeout=1, upload_idle_timeout=.1)

    async def slow():
        for _ in range(3):
            await asyncio.sleep(.05)
            yield b"x"

    ref = await store.upload(slow(), owner="owner", mime="image/png", size=3)
    assert Path(store.commit([ref], owner="owner")[0]).read_bytes() == b"xxx"


async def test_stalled_upload_releases_file_and_capacity(tmp_path):
    store = AttachmentStore(
        tmp_path, upload_timeout=1, upload_idle_timeout=.01,
        max_pending=1, max_pending_bytes=2,
    )

    async def stalled():
        yield b"x"
        await asyncio.Event().wait()

    with pytest.raises(TimeoutError):
        await store.upload(stalled(), owner="owner", mime="image/png", size=2)
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]
    assert await upload(store, b"xx")


async def test_expiry_cleans_only_staged_files(tmp_path, monkeypatch):
    import nanobot.channels.websocket.attachment_store as module
    monkeypatch.setattr(module.time, "monotonic", lambda: 100)
    store = AttachmentStore(tmp_path, ttl_seconds=10)
    committed = await upload(store)
    staged = await upload(store)
    keep = Path(store.commit([committed], owner="owner")[0])
    remove = Path(store.resolve([staged], owner="owner")[0])
    monkeypatch.setattr(module.time, "monotonic", lambda: 111)
    store.prune()
    assert keep.exists()
    assert not remove.exists()
    with pytest.raises(AttachmentUploadError):
        store.resolve([staged], owner="owner")


async def test_batch_limits_leave_all_references_retryable(tmp_path):
    store = AttachmentStore(tmp_path, limits=AttachmentIngressLimits(
        max_count=2, max_file_bytes=10, max_total_bytes=10,
    ))
    refs = [await upload(store, b"123456") for _ in range(2)]
    with pytest.raises(AttachmentUploadError, match="total"):
        store.commit(refs, owner="owner")
    for ref in refs:
        assert store.resolve([ref], owner="owner")
    videos = [await upload(store, mime="video/mp4") for _ in range(2)]
    with pytest.raises(AttachmentUploadError, match="Too many"):
        store.resolve(videos, owner="owner")
    store.clear()
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


async def test_filename_collision_never_unlinks_existing_file(tmp_path, monkeypatch):
    import nanobot.channels.websocket.attachment_store as module
    existing = tmp_path / "existing.png"
    existing.write_bytes(b"keep")
    monkeypatch.setattr(module, "media_destination", lambda *args, **kwargs: existing)
    with pytest.raises(FileExistsError):
        await upload(AttachmentStore(tmp_path))
    assert existing.read_bytes() == b"keep"


async def test_committed_paths_persist_and_replay_without_reference_format(tmp_path):
    from nanobot.session.manager import SessionManager

    store = AttachmentStore(tmp_path / "media")
    reference = await upload(store)
    paths = store.commit([reference], owner="owner")
    manager = SessionManager(tmp_path / "workspace")
    session = manager.get_or_create("websocket:binary-upload")
    session.add_message("user", "look", media=paths)
    manager.save(session)

    replay_manager = SessionManager(tmp_path / "workspace")
    replay = replay_manager.get_or_create("websocket:binary-upload")
    assert replay.messages[0]["media"] == paths
    assert reference not in str(replay.messages)
    assert replay.get_history()[0] == {
        "role": "user", "content": f"look\n[image: {paths[0]}]",
    }
    store.clear()
    assert Path(paths[0]).exists()


async def test_restart_prunes_crash_remnants_but_not_committed_media(tmp_path, monkeypatch):
    import os
    import time

    first = AttachmentStore(tmp_path)
    committed = await upload(first)
    keep = Path(first.commit([committed], owner="owner")[0])
    abandoned = await upload(first)
    remove = Path(first.resolve([abandoned], owner="owner")[0])
    marker = tmp_path / ".pending-attachments" / remove.name
    old = time.time() - first.ttl_seconds - first.upload_timeout - 1
    os.utime(marker, (old, old))
    restarted = AttachmentStore(tmp_path)
    restarted.prune()
    assert not remove.exists()
    assert not marker.exists()
    assert keep.read_bytes() == b"attachment"


async def test_disconnect_releases_staged_capacity_but_preserves_commits(tmp_path):
    store = AttachmentStore(tmp_path, max_pending=1)
    ref = await upload(store)
    keep = Path(store.commit([ref], owner="owner")[0])
    ref = await upload(store)
    remove = Path(store.resolve([ref], owner="owner")[0])
    store.discard_owner("owner")
    assert not remove.exists()
    assert keep.exists()
    assert await upload(store)


async def test_filename_collision_preserves_another_uploads_crash_marker(tmp_path, monkeypatch):
    store = AttachmentStore(tmp_path)
    ref = await upload(store)
    path = Path(store.resolve([ref], owner="owner")[0])
    monkeypatch.setattr("nanobot.channels.websocket.attachment_store.media_destination", lambda *args, **kwargs: path)
    with pytest.raises(FileExistsError):
        await upload(store)
    assert (tmp_path / ".pending-attachments" / path.name).exists()
    assert path.read_bytes() == b"attachment"
    store.clear()
