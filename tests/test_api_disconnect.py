"""HTTP connection ownership with the real AgentLoop and an offline model.

Only the model is controlled: requests enter through authenticated TCP sockets,
including when no response body has been generated yet.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shlex
import subprocess
import sys
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, field

import pytest
from aiohttp import ClientSession, web

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import current_request_context
from nanobot.api.server import create_app
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

pytestmark = pytest.mark.asyncio
API_KEY = "offline-disconnect-test"
AUTH = {"Authorization": f"Bearer {API_KEY}"}


@dataclass
class ModelWork:
    hold: bool = False
    delta: str = ""
    checkpoint_tool: bool = False
    exec_command: str | None = None
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    cleanup_started: asyncio.Event = field(default_factory=asyncio.Event)
    release_cleanup: asyncio.Event = field(default_factory=asyncio.Event)
    cleanup_completed: asyncio.Event = field(default_factory=asyncio.Event)
    exited: asyncio.Event = field(default_factory=asyncio.Event)


class ControlledProvider(LLMProvider):
    def __init__(self, work):
        super().__init__(provider_name="offline-disconnect")
        self.work = work
        self.active = set()
        self.messages = {}

    def get_default_model(self):
        return "offline-disconnect"

    async def chat(self, messages, tools=None, **kwargs):
        return await self.chat_stream(messages, tools, **kwargs)

    async def chat_stream(self, messages, tools=None, on_content_delta=None, **kwargs):
        context = current_request_context()
        assert context is not None
        text = context.original_user_text
        work = self.work.setdefault(text, ModelWork())
        self.messages[text] = deepcopy(messages)
        if work.exec_command and messages[-1]["role"] != "tool":
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="foreground-process", name="exec",
                arguments={"command": work.exec_command, "yield_time_ms": 30000, "max_runtime": 60},
            )])
        if work.checkpoint_tool and messages[-1]["role"] != "tool":
            return LLMResponse(content="checking route", tool_calls=[ToolCallRequest(
                id="inspect-route", name="my",
                arguments={"action": "check", "key": "request.chat_id"},
            )])
        self.active.add(text)
        work.started.set()
        try:
            if on_content_delta and work.delta:
                await on_content_delta(work.delta)
            if work.hold:
                await work.release.wait()
            return LLMResponse(content=f"completed:{text}")
        except asyncio.CancelledError:
            work.cancelled.set()
            raise
        finally:
            work.cleanup_started.set()
            try:
                if work.hold:
                    await work.release_cleanup.wait()
                work.cleanup_completed.set()
            finally:
                self.active.remove(text)
                work.exited.set()


async def reached(event):
    # A test failure bound, not a production disconnect/cleanup timeout.
    await asyncio.wait_for(event.wait(), 10)


@asynccontextmanager
async def runtime(tmp_path, monkeypatch, work, *, request_timeout=120, restrict_to_workspace=True):
    for variable, name in (
        ("HOME", "home"), ("XDG_CONFIG_HOME", "xdg-config"),
        ("XDG_CACHE_HOME", "xdg-cache"), ("XDG_DATA_HOME", "xdg-data"),
    ):
        directory = tmp_path / name
        directory.mkdir()
        monkeypatch.setenv(variable, str(directory))
    from nanobot.apps.cli import service as cli_apps
    from nanobot.config import home, loader

    instance = tmp_path / "instance"
    instance.mkdir()
    monkeypatch.setenv("NANOBOT_HOME", str(instance))
    monkeypatch.setenv("NANOBOT_CONFIG", str(instance / "config.json"))
    monkeypatch.setenv("NANOBOT_CLI_APPS_ROOT", str(instance / "cli-apps"))
    monkeypatch.setattr(home, "_home_path", instance)
    monkeypatch.setattr(loader, "_current_config_path", instance / "config.json")
    monkeypatch.setattr(cli_apps, "get_runtime_subdir", lambda name: instance / name)
    provider = ControlledProvider(work)
    agent = AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path / "workspace",
        restrict_to_workspace=restrict_to_workspace, max_iterations=3,
    )
    entered = {}
    finished = {}
    app = create_app(agent, api_key=API_KEY, request_timeout=request_timeout)

    @web.middleware
    async def observe_lifetime(request, handler):
        body = await request.json()
        text = body["messages"][0]["content"]
        entered.setdefault(text, asyncio.Event()).set()
        try:
            return await handler(request)
        finally:
            finished.setdefault(text, asyncio.Event()).set()

    app.middlewares.append(observe_lifetime)
    # TestServer enables handler_cancellation itself, hiding a missing production
    # app setting. Use the same runner default as `nanobot serve` / web.run_app.
    runner = web.AppRunner(app, handler_cancellation=False)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0]
    client = ClientSession(base_url=f"http://{host}:{port}")
    sockets = []
    tasks = []

    async def connect(text, session_id, stream):
        reader, writer = await asyncio.open_connection(host, port)
        sockets.append(writer)
        body = json.dumps({
            "messages": [{"role": "user", "content": text}],
            "session_id": session_id, "stream": stream,
        }).encode()
        writer.write(
            f"POST /v1/chat/completions HTTP/1.1\r\nHost: {host}\r\n"
            f"Authorization: Bearer {API_KEY}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n\r\n".encode() + body
        )
        await writer.drain()
        await reached(entered.setdefault(text, asyncio.Event()))
        if stream:
            headers = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            assert headers.startswith(b"HTTP/1.1 200")
            assert b"Content-Type: text/event-stream" in headers
        return reader, writer

    async def post(text, session_id):
        response = await client.post(
            "/v1/chat/completions", headers=AUTH,
            json={"messages": [{"role": "user", "content": text}], "session_id": session_id},
        )
        assert response.status == 200, await response.text()
        assert (await response.json())["choices"][0]["message"]["content"] == f"completed:{text}"

    def start_post(text, session_id):
        task = asyncio.create_task(post(text, session_id))
        tasks.append(task)
        return task

    try:
        yield provider, connect, start_post, entered, finished
    finally:
        # Release every controlled resource even after a regression assertion fails.
        for item in work.values():
            item.release.set()
            item.release_cleanup.set()
        for writer in sockets:
            writer.close()
            await writer.wait_closed()
        await asyncio.gather(*tasks, return_exceptions=True)
        await client.close()
        await runner.cleanup()
        await agent.aclose()
        assert not provider.active


@pytest.mark.parametrize("stream,delta", [(False, ""), (True, ""), (True, "partial")],
                         ids=["json-before-result", "sse-before-token", "sse-midstream"])
async def test_disconnect_cancels_only_owned_work_and_waits_for_cleanup(
    tmp_path, monkeypatch, stream, delta,
):
    target = ModelWork(hold=True, delta=delta)
    other = ModelWork(hold=True)
    following = ModelWork()
    work = {"TARGET": target, "OTHER": other, "FOLLOWING": following}
    async with runtime(tmp_path, monkeypatch, work) as (
        provider, connect, start_post, entered, finished,
    ):
        reader, writer = await connect("TARGET", "shared", stream)
        await reached(target.started)
        if delta:
            await asyncio.wait_for(reader.readuntil(b'"content": "partial"'), 10)
        other_request = start_post("OTHER", "independent")
        await reached(other.started)
        following_request = start_post("FOLLOWING", "shared")
        await reached(entered.setdefault("FOLLOWING", asyncio.Event()))
        assert not following.started.is_set()

        writer.close()  # Real TCP EOF, not a private cancellation method.
        await writer.wait_closed()
        await reached(target.cleanup_started)
        assert target.cancelled.is_set()
        assert not target.exited.is_set()
        assert not finished.setdefault("TARGET", asyncio.Event()).is_set()
        assert not following.started.is_set()
        assert provider.active == {"TARGET", "OTHER"}
        assert not other.cancelled.is_set()

        # Another owner can complete while the disconnected owner's cleanup waits.
        other.release.set()
        other.release_cleanup.set()
        await asyncio.wait_for(other_request, 10)
        assert other.exited.is_set()
        assert not other.cancelled.is_set()
        assert not target.exited.is_set()

        target.release_cleanup.set()
        await reached(target.exited)
        assert target.cleanup_completed.is_set()
        await reached(finished["TARGET"])
        await asyncio.wait_for(following_request, 10)
        assert not following.cancelled.is_set()
        assert not provider.active
        await asyncio.wait_for(start_post("NEXT", "next-independent"), 10)


@pytest.mark.parametrize("stream", [False, True], ids=["json-queued", "sse-queued"])
async def test_disconnected_session_waiter_never_cancels_current_owner(
    tmp_path, monkeypatch, stream,
):
    owner = ModelWork(hold=True)
    waiting = ModelWork()
    work = {"OWNER": owner, "WAITING": waiting}
    async with runtime(tmp_path, monkeypatch, work) as (
        _, connect, start_post, _, finished,
    ):
        current = start_post("OWNER", "same-session")
        await reached(owner.started)
        _, writer = await connect("WAITING", "same-session", stream)
        assert not waiting.started.is_set()
        writer.close()
        await writer.wait_closed()
        await reached(finished.setdefault("WAITING", asyncio.Event()))
        assert not owner.cancelled.is_set()
        assert not owner.exited.is_set()
        assert not waiting.started.is_set()

        owner.release.set()
        owner.release_cleanup.set()
        await asyncio.wait_for(current, 10)
        await asyncio.wait_for(start_post("AFTER", "same-session"), 10)
        assert not owner.cancelled.is_set()
        assert not waiting.started.is_set()


async def test_disconnect_preserves_completed_tool_checkpoint_for_next_request(tmp_path, monkeypatch):
    interrupted = ModelWork(hold=True, checkpoint_tool=True)
    work = {"INTERRUPTED": interrupted}
    async with runtime(tmp_path, monkeypatch, work) as (
        provider, connect, start_post, _, finished,
    ):
        _, writer = await connect("INTERRUPTED", "checkpoint-session", True)
        # This milestone is the second model call, after the real my tool and its
        # completed result checkpoint, not merely an emitted token.
        await reached(interrupted.started)
        assert provider.messages["INTERRUPTED"][-1]["role"] == "tool"
        assert provider.messages["INTERRUPTED"][-1]["content"] == "request.chat_id: 'checkpoint-session'"
        writer.close()
        await writer.wait_closed()
        await reached(interrupted.cleanup_started)
        assert interrupted.cancelled.is_set()
        interrupted.release_cleanup.set()
        await reached(finished.setdefault("INTERRUPTED", asyncio.Event()))

        await asyncio.wait_for(start_post("RECOVERED", "checkpoint-session"), 10)
        replay = provider.messages["RECOVERED"]
        assert any(message["role"] == "user" and "INTERRUPTED" in str(message["content"])
                   for message in replay)
        assert any(message["role"] == "assistant" and message.get("tool_calls")
                   for message in replay)
        assert any(message["role"] == "tool" and
                   message["content"] == "request.chat_id: 'checkpoint-session'"
                   for message in replay)


@pytest.mark.parametrize("stream", [False, True], ids=["json-timeout-cleanup", "sse-timeout-cleanup"])
async def test_disconnect_during_timeout_does_not_interrupt_owned_cleanup(tmp_path, monkeypatch, stream):
    interrupted = ModelWork(hold=True)
    work = {"TIMED_OUT": interrupted}
    async with runtime(tmp_path, monkeypatch, work, request_timeout=1) as (
        _, connect, start_post, _, finished,
    ):
        _, writer = await connect("TIMED_OUT", "timeout-session", stream)
        await reached(interrupted.started)
        # The configured API timeout starts real model cleanup before TCP loss.
        await reached(interrupted.cleanup_started)
        assert interrupted.cancelled.is_set()
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(start_post("DURING_CLEANUP", "independent"), 10)
        assert not interrupted.exited.is_set()
        assert not finished.setdefault("TIMED_OUT", asyncio.Event()).is_set()
        interrupted.release_cleanup.set()
        await reached(finished["TIMED_OUT"])
        assert interrupted.cleanup_completed.is_set()
        assert interrupted.exited.is_set()
        await asyncio.wait_for(start_post("AFTER_TIMEOUT", "timeout-session"), 10)


@pytest.mark.parametrize("stream", [False, True], ids=["json-foreground-tool", "sse-foreground-tool"])
async def test_disconnect_reaps_real_foreground_tool_process(tmp_path, monkeypatch, stream, record_property):
    started = asyncio.Event()
    peer_closed = asyncio.Event()
    peers = []
    pids = []
    token = secrets.token_hex(16)

    async def observe_process(reader, writer):
        peers.append(writer)
        try:
            hello = json.loads(await reader.readline())
            assert hello["token"] == token
            pids.append(hello["pid"])
            started.set()
            # EOF is produced by the actual tool process exiting, not a mock
            # tool result or a cancellation acknowledgement.
            assert await reader.read() == b""
        finally:
            writer.close()
            await writer.wait_closed()
            peer_closed.set()

    listener = await asyncio.start_server(observe_process, "127.0.0.1", 0)
    port = listener.sockets[0].getsockname()[1]
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "owned_worker.py").write_text(
        "import json, os, socket, sys\n"
        "with socket.create_connection(('127.0.0.1', int(sys.argv[1]))) as peer:\n"
        "    peer.sendall((json.dumps({'token': sys.argv[2], 'pid': os.getpid()}) + '\\n').encode())\n"
        "    while peer.recv(1):\n"
        "        pass\n",
        encoding="utf-8",
    )
    argv = [sys.executable, "-u", "owned_worker.py", str(port), token]
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    work = {"TOOL": ModelWork(exec_command=command)}
    try:
        # The configured unrestricted shell permits the isolated interpreter
        # outside the workspace; the worker itself only uses this private tmp_path.
        async with runtime(tmp_path, monkeypatch, work, restrict_to_workspace=False) as (
            provider, connect, start_post, _, finished,
        ):
            _, writer = await connect("TOOL", "tool-session", stream)
            try:
                await reached(started)
            except TimeoutError:
                pytest.fail(f"tool did not start: {provider.messages.get('TOOL', [])[-1:]}")
            assert not peer_closed.is_set()
            await asyncio.wait_for(start_post("BESIDE_TOOL", "independent"), 10)
            writer.close()
            await writer.wait_closed()
            await reached(finished.setdefault("TOOL", asyncio.Event()))
            await reached(peer_closed)
            assert len(pids) == 1
            record_property("owned_tool_pid", pids[0])
            record_property("loopback_port", port)
            record_property("process_transport_eof", True)
            if os.name != "nt":
                # After handler settlement, the owned child must be reaped too.
                with pytest.raises(ProcessLookupError):
                    os.kill(pids[0], 0)
                record_property("pid_reaped", True)
            await asyncio.wait_for(start_post("AFTER_TOOL", "tool-session"), 10)
    finally:
        for peer in peers:
            peer.close()
            await peer.wait_closed()
        listener.close()
        await listener.wait_closed()
