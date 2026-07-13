from __future__ import annotations

import asyncio
import threading

from nanobot.channels._feishu_ws import FeishuWsRunner


def test_concurrent_loop_initialization_starts_one_thread(monkeypatch) -> None:
    runner = FeishuWsRunner()
    created_loops: list[asyncio.AbstractEventLoop] = []
    release_start = threading.Event()

    def fake_run_loop() -> None:
        loop = asyncio.new_event_loop()
        created_loops.append(loop)
        assert release_start.wait(timeout=2)
        runner._loop = loop
        runner._ready.set()

    monkeypatch.setattr(runner, "_run_loop", fake_run_loop)
    loops: list[asyncio.AbstractEventLoop] = []
    threads = [threading.Thread(target=lambda: loops.append(runner._ensure_loop())) for _ in range(2)]

    for thread in threads:
        thread.start()
    release_start.set()
    for thread in threads:
        thread.join(timeout=2)

    assert len(created_loops) == 1
    assert loops == [created_loops[0], created_loops[0]]
    created_loops[0].close()
