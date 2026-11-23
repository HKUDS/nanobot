import asyncio
from unittest.mock import MagicMock, patch

import pytest

from nanobot.cli import stream


@pytest.fixture(autouse=True)
def fixed_arrival_time():
    # Keep a burst inside one refresh window without changing asyncio's timer clock.
    with patch.object(stream, "time") as clock:
        clock.monotonic.return_value = 0.0
        yield


@pytest.mark.asyncio
async def test_stream_coalesces_burst_and_flushes_during_provider_pause():
    with patch.object(stream, "Live") as live_class, patch.object(stream, "_make_console"):
        live = live_class.return_value
        renderer = stream.StreamRenderer(show_spinner=False)
        await renderer.on_delta("first")
        live.refresh.assert_called_once()
        for _ in range(100):
            await renderer.on_delta(" token")
        live.update.assert_not_called()
        await asyncio.sleep(stream._STREAM_REFRESH_INTERVAL * 2)
        live.update.assert_called_once()
        assert live.update.call_args.args[0].markup == "first" + " token" * 100
        assert live.refresh.call_count == 2
        await renderer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["end", "close", "pause"])
async def test_pending_refresh_cannot_write_after_stream_teardown(finish):
    with patch.object(stream, "Live") as live_class, patch.object(stream, "_make_console"):
        live = live_class.return_value
        renderer = stream.StreamRenderer(show_spinner=False)
        await renderer.on_delta("first")
        await renderer.on_delta(" last")
        handle = renderer._refresh_handle
        assert handle is not None
        if finish == "end":
            with patch.object(renderer, "_render_str", return_value="first last\n"), \
                 patch.object(stream.sys, "stdout") as output:
                await renderer.on_end(resuming=True)
                output.write.assert_called_once_with("first last\n")
            assert renderer._buf == ""
        elif finish == "close":
            await renderer.close()
        else:
            with renderer.pause_spinner():
                pass
            assert renderer._buf == "first last"
        assert handle.cancelled()
        live.reset_mock()
        await asyncio.sleep(stream._STREAM_REFRESH_INTERVAL * 2)
        live.update.assert_not_called()
        live.refresh.assert_not_called()
        await renderer.close()


@pytest.mark.asyncio
async def test_resuming_after_trace_renders_the_buffered_tail():
    with patch.object(stream, "Live") as live_class, patch.object(stream, "_make_console"):
        live_class.side_effect = [MagicMock(), MagicMock()]
        renderer = stream.StreamRenderer(show_spinner=False)
        await renderer.on_delta("before")
        await renderer.on_delta(" trace")
        with renderer.pause_spinner():
            pass
        await renderer.on_delta(" after")
        assert live_class.call_args.args[0].markup == "before trace after"
        await renderer.close()
