"""Private SSH master lifetime and guarded-bridge compatibility."""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nanobot.webui import remote_mux, remote_ssh
from nanobot.webui.remote_mux import SSHMaster
from nanobot.webui.remote_ssh import PairedSSHProfile, RemoteError


@pytest.fixture
def master_child(monkeypatch):
    real_spawn = asyncio.create_subprocess_exec
    children, commands = [], []
    state = {"fail": False, "gate": None, "started": asyncio.Event()}

    async def spawn(*args, **kwargs):
        commands.append(args)
        path = next(arg.split("=", 1)[1] for arg in args if arg.startswith("ControlPath="))
        script = ("import sys;sys.stderr.write('Permission denied');sys.exit(255)" if state["fail"] else
                  "import socket,sys,time;s=socket.socket(socket.AF_UNIX);s.bind(sys.argv[1]);s.listen();time.sleep(120)")
        child = await real_spawn(sys.executable, "-u", "-c", script, path, **kwargs)
        children.append(child)
        state["started"].set()
        if state["gate"] is not None:
            await state["gate"].wait()
        return child

    monkeypatch.setattr(remote_mux.asyncio, "create_subprocess_exec", spawn)
    return state, children, commands


@pytest.mark.skipif(os.name == "nt", reason="OpenSSH control sockets require Unix")
async def test_parallel_channels_share_only_owned_master_and_close_cleans_it(master_child):
    _, children, commands = master_child
    master = SSHMaster(["ssh", "-o", "ControlMaster=no", "-o", "ControlPath=none"], "pinned-host")
    channel = ["ssh", "-o", "ControlPath=none", "-W", "127.0.0.1:8765", "pinned-host"]
    paths = []
    try:
        results = await asyncio.gather(*(master.arguments(channel) for _ in range(8)))
        assert len(children) == 1
        paths = [Path(result[2]) for result in results]
        assert len(set(paths)) == 1 and paths[0].exists()
        assert paths[0].parent.stat().st_mode & 0o777 == 0o700
        assert commands[0][-2:] == ("-N", "pinned-host")
        assert "ControlPersist=no" in commands[0]
        assert all(result[3:] == channel[1:] for result in results)
        await master.close()
        assert children[0].returncode is not None
        assert not paths[0].parent.exists()
        renewed = await master.arguments(channel)
        assert renewed[2] != str(paths[0]) and len(children) == 2
    finally:
        await master.close()
    assert all(child.returncode is not None for child in children)


@pytest.mark.skipif(os.name == "nt", reason="OpenSSH control sockets require Unix")
async def test_dead_master_reauthenticates_and_does_not_share_other_connections(master_child):
    _, children, _ = master_child
    first = SSHMaster(["ssh"], "host")
    second = SSHMaster(["ssh"], "host")
    channel = ["ssh", "host", "bridge"]
    try:
        original = await first.arguments(channel)
        isolated = await second.arguments(channel)
        assert original[2] != isolated[2]
        children[0].terminate()
        await children[0].wait()
        renewed = await first.arguments(channel)
        assert len(children) == 3
        assert renewed[2] not in (original[2], isolated[2])
        assert not Path(original[2]).parent.exists()
        assert children[1].returncode is None
        assert await second.arguments(channel) == isolated
    finally:
        await first.close()
        await second.close()
    assert all(child.returncode is not None for child in children)


@pytest.mark.skipif(os.name == "nt", reason="OpenSSH control sockets require Unix")
async def test_long_socket_path_falls_back_without_starting_a_master(tmp_path, monkeypatch, master_child):
    _, children, _ = master_child
    directory = tmp_path / ("long-" * 25)
    directory.mkdir()
    monkeypatch.setattr(remote_mux.tempfile, "tempdir", str(directory))
    master = SSHMaster(["ssh"], "host")
    channel = ["ssh", "host", "bridge"]
    assert await master.arguments(channel) == channel
    assert master._directory is None
    assert children == []
    assert list(directory.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="OpenSSH control sockets require Unix")
async def test_failed_authentication_is_not_hidden_by_fallback(master_child):
    state, children, _ = master_child
    state["fail"] = True
    master = SSHMaster(["ssh"], "host")
    with pytest.raises(RemoteError, match="ssh_auth_failed"):
        await master.arguments(["ssh", "host", "bridge"])
    assert master._directory is None
    assert children[0].returncode == 255


@pytest.mark.skipif(os.name == "nt", reason="OpenSSH control sockets require Unix")
async def test_cancel_during_master_spawn_reaps_process_and_socket(master_child):
    state, children, _ = master_child
    state["gate"] = asyncio.Event()
    master = SSHMaster(["ssh"], "host")
    task = asyncio.create_task(master.arguments(["ssh", "host", "bridge"]))
    await state["started"].wait()
    task.cancel()
    state["gate"].set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert master._directory is None
    assert all(child.returncode is not None for child in children)


@pytest.mark.parametrize("guarded", [False, True])
@pytest.mark.parametrize("loses_guard", [False, True])
async def test_paired_tunnel_reuses_only_after_guarded_bridge_marker(tmp_path, monkeypatch, guarded, loses_guard):
    real_spawn = asyncio.create_subprocess_exec
    known = tmp_path / "known_hosts"
    known.write_text("pinned fixture")
    masters = []

    class Master:
        def __init__(self, *args):
            self.arguments = AsyncMock(side_effect=lambda channel: channel)
            self.close = AsyncMock()
            masters.append(self)

    monkeypatch.setattr(remote_ssh, "SSHMaster", Master)
    monkeypatch.setattr(remote_ssh.shutil, "which", lambda _: "fixture-ssh")
    children = []
    script = (f"import os\nos.write(1, {remote_ssh._BRIDGE_READY!r})\n" if guarded else "import os\n")
    script += "while data := os.read(0,65536):\n os.write(1,data)\n"

    async def spawn(*args, **kwargs):
        source = script
        if loses_guard and len(children) >= 1:
            source = "import os\nwhile data := os.read(0,65536):\n os.write(1,data)\n"
        child = await real_spawn(sys.executable, "-u", "-c", source, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    profile = PairedSSHProfile(name="Fixture", host="fixture.test")
    tunnel = await remote_ssh.open_tunnel(profile, 8765, known)
    try:
        for _ in range(3):
            reader, writer = await asyncio.open_connection("127.0.0.1", tunnel.port)
            writer.write(b"HTTP/1.1 200 OK\r\nbody")
            await writer.drain()
            writer.write_eof()
            assert await asyncio.wait_for(reader.read(), 5) == b"HTTP/1.1 200 OK\r\nbody"
            writer.close()
            await writer.wait_closed()
        if guarded and os.name != "nt":
            assert len(masters) == 1
            assert masters[0].arguments.await_count == (2 if loses_guard else 3)
        elif os.name != "nt":
            assert len(masters) == 1
            assert masters[0].arguments.await_count == 1
        else:
            assert masters == []
    finally:
        await tunnel.close()
    assert all(child.returncode is not None for child in children)
    if masters:
        masters[0].close.assert_awaited_once()
