import asyncio
from contextlib import suppress
from pathlib import Path

import pytest
from watchfiles import Change

import nanobot.config.watcher as config_watcher


@pytest.mark.asyncio
async def test_watch_config_file_filters_directory_events(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.json"
    other_path = tmp_path / "other.json"
    seen: dict[str, object] = {}

    async def fake_awatch(*paths, **kwargs):
        seen["paths"] = paths
        seen["recursive"] = kwargs["recursive"]
        watch_filter = kwargs["watch_filter"]
        assert watch_filter(Change.modified, str(config_path)) is True
        assert watch_filter(Change.modified, str(other_path)) is False
        yield {(Change.modified, str(config_path))}

    monkeypatch.setattr(config_watcher, "awatch", fake_awatch)
    changes: list[None] = []

    await config_watcher.watch_config_file(config_path, lambda: changes.append(None))

    assert seen == {"paths": (tmp_path,), "recursive": False}
    assert changes == [None]


@pytest.mark.asyncio
async def test_watch_config_file_observes_atomic_replace(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    changed = asyncio.Event()
    task = asyncio.create_task(
        config_watcher.watch_config_file(config_path, changed.set)
    )

    try:
        for attempt in range(10):
            replacement = tmp_path / "config.tmp"
            replacement.write_text(f'{{"attempt": {attempt}}}', encoding="utf-8")
            replacement.replace(config_path)
            try:
                await asyncio.wait_for(changed.wait(), timeout=0.2)
                break
            except TimeoutError:
                continue
        assert changed.is_set()
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
