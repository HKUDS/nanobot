"""Real stdio MCP contract, without requesting any desktop permission."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from nanobot.agent.tools.context import current_tool_run, tool_run_scope
from nanobot.apps.computer_use_native import NativeConnection, register_package
from nanobot.apps.computer_use_turn import NativeTurnTransport


@pytest.fixture
def socket_path():
    if sys.platform == "win32":
        pytest.skip("Native host transport uses macOS/POSIX asyncio Unix sockets")
    # macOS AF_UNIX paths are limited to 104 bytes; pytest's nested tmp_path is longer.
    with tempfile.TemporaryDirectory(prefix="nb-native-", dir="/tmp") as directory:
        yield Path(directory) / "native.sock"


def test_staging_native_build_does_not_hide_previous_driver_install(tmp_path):
    from nanobot.apps.cua_driver import CuaDriver
    from nanobot.config.loader import save_config
    from nanobot.config.schema import Config

    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    driver = CuaDriver(config_path)
    driver.directory.mkdir(parents=True)
    with pytest.raises(ValueError, match="Uninstall the current"):
        register_package(config_path, tmp_path / "new-manifest.json")
    assert driver.directory.exists()


@pytest.mark.asyncio
async def test_native_task_scope_is_shared_by_tools_isolated_by_run_and_closed_on_cancel():
    session = AsyncMock()
    transport = NativeTurnTransport(session)
    with pytest.raises(RuntimeError, match="gateway-owned"):
        await transport.call_tool("click", {})
    async with tool_run_scope() as first:
        await transport.call_tool("get_window_state", {"pid": 10, "window_id": 20})
        await transport.call_tool("click", {"element_index": 2})
        assert [call.kwargs["meta"] for call in session.call_tool.call_args_list] == [{"nanobot/turn": first.id}] * 2
    assert session.call_tool.call_args.args == ("nanobot_finish_turn",)
    with pytest.raises(asyncio.CancelledError):
        async with tool_run_scope() as second:
            assert first.id != second.id
            await transport.call_tool("get_window_state", {})
            raise asyncio.CancelledError
    assert session.call_tool.call_args.kwargs["meta"] == {"nanobot/turn": second.id}
    assert not transport.scopes and current_tool_run() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [False, True])
async def test_stdio_mcp_passes_only_host_owned_task_scope_and_releases_channel(socket_path, malformed):
    address = socket_path
    requests = []
    closed = asyncio.Event()

    async def host(reader, writer):
        was_call = False
        try:
            while line := await reader.readline():
                req = json.loads(line)
                requests.append(req)
                if req["method"] == "list":
                    result = {"tools": [{"name": "get_window_state", "inputSchema": {"type": "object"}}]}
                else:
                    was_call = True
                    result = {"content": [{"type": "text", "text": "window result"}], "isError": False}
                    if malformed:
                        result = {"content": [{"type": "invalid"}]}
                writer.write(json.dumps({"ok": True, "result": result}).encode() + b"\n")
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            if was_call:
                closed.set()

    listener = await asyncio.start_unix_server(host, str(address))
    try:
        async with stdio_client(StdioServerParameters(command=sys.executable, args=["-m", "nanobot.apps.computer_use_mcp", str(address)])) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                assert [tool.name for tool in (await session.list_tools()).tools] == ["get_window_state"]
                refused = await session.call_tool("get_window_state", {"session": "model-provided"})
                assert refused.isError
                assert not any(r["method"] == "call" for r in requests)
                transport = NativeTurnTransport(session)
                async with tool_run_scope():
                    result = await transport.call_tool("get_window_state", {"pid": 10, "window_id": 20})
                    assert bool(result.isError) is malformed
                    if malformed:
                        # A malformed SDK reply must release its active window
                        # immediately, not leak it until the idle deadline.
                        await asyncio.wait_for(closed.wait(), 2)
                    else:
                        assert not closed.is_set()
                await asyncio.wait_for(closed.wait(), 2)
    finally:
        listener.close()
        await listener.wait_closed()


@pytest.mark.asyncio
async def test_cancelling_native_request_closes_socket_without_replay(socket_path):
    address = socket_path
    received, closed = asyncio.Event(), asyncio.Event()
    count = 0

    async def host(reader, writer):
        nonlocal count
        if await reader.readline():
            count += 1
            received.set()
        await reader.read()
        closed.set()
        writer.close()
        await writer.wait_closed()

    listener = await asyncio.start_unix_server(host, str(address))
    try:
        connection = NativeConnection(address)
        task = asyncio.create_task(connection.request("call", name="click"))
        await received.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(closed.wait(), 2)
        assert count == 1 and connection.writer is None
    finally:
        listener.close()
        await listener.wait_closed()
