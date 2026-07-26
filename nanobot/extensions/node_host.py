"""Async process boundary for untrusted-compatible JavaScript extension APIs."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from contextlib import suppress
from pathlib import Path
from typing import Any

from nanobot.extensions.protocol import (
    NODE_PROTOCOL_VERSION,
    NodeLoadResult,
    NodeProtocolError,
)


class NodeSidecar:
    """One isolated Node process hosting one extension module."""

    def __init__(
        self,
        *,
        node: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._node = node or os.getenv("NANOBOT_NODE") or shutil.which("node")
        self._timeout = timeout
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._stderr_reader: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._write_lock = asyncio.Lock()
        self._next_id = 0
        self.stderr: list[str] = []

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        if self.running:
            return
        if not self._node:
            raise NodeProtocolError(
                "Node.js is required for Pi and OpenClaw extensions; "
                "install Node.js 20+ or set NANOBOT_NODE"
            )
        script = Path(__file__).with_name("node_sidecar.mjs")
        self._process = await asyncio.create_subprocess_exec(
            self._node,
            str(script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader = asyncio.create_task(self._read_stdout())
        self._stderr_reader = asyncio.create_task(self._read_stderr())
        hello = await self.request("hello", {})
        if hello.get("protocol") != NODE_PROTOCOL_VERSION:
            await self.close()
            raise NodeProtocolError(
                f"sidecar protocol mismatch: expected {NODE_PROTOCOL_VERSION}"
            )

    async def load(
        self,
        *,
        runtime: str,
        entries: tuple[Path, ...],
        root: Path,
        extension_id: str,
        name: str,
        version: str,
        config: dict[str, Any] | None = None,
        workspace: Path | None = None,
    ) -> NodeLoadResult:
        await self.start()
        result = await self.request(
            "extension.load",
            {
                "runtime": runtime,
                "entries": [
                    str(entry.expanduser().resolve()) for entry in entries
                ],
                "root": str(root.expanduser().resolve()),
                "identity": {
                    "id": extension_id,
                    "name": name,
                    "version": version,
                },
                "config": config or {},
                "workspace": str((workspace or Path.cwd()).resolve()),
            },
        )
        return NodeLoadResult.from_mapping(result)

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if method != "hello" and not self.running:
            raise NodeProtocolError("sidecar is not running")
        process = self._process
        if process is None or process.stdin is None:
            raise NodeProtocolError("sidecar failed to start")

        self._next_id += 1
        request_id = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        message = json.dumps(
            {
                "protocol": NODE_PROTOCOL_VERSION,
                "id": request_id,
                "method": method,
                "params": params,
            },
            separators=(",", ":"),
        ).encode()
        try:
            async with self._write_lock:
                process.stdin.write(message + b"\n")
                await process.stdin.drain()
            result = await asyncio.wait_for(future, timeout or self._timeout)
        except Exception:
            self._pending.pop(request_id, None)
            raise
        if not isinstance(result, dict):
            raise NodeProtocolError(f"sidecar method {method!r} returned a non-object result")
        return result

    async def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.returncode is None:
            with suppress(Exception):
                await self.request("shutdown", {}, timeout=2.0)
        if process.returncode is None:
            process.terminate()
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), 2.0)
        if process.returncode is None:
            process.kill()
            await process.wait()
        for task in (self._reader, self._stderr_reader):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        self._fail_pending(NodeProtocolError("sidecar closed"))
        self._process = None

    async def _read_stdout(self) -> None:
        assert self._process and self._process.stdout
        try:
            while line := await self._process.stdout.readline():
                try:
                    message = json.loads(line)
                    request_id = message["id"]
                    future = self._pending.pop(request_id)
                    if error := message.get("error"):
                        future.set_exception(
                            NodeProtocolError(
                                f"{error.get('code', 'sidecar_error')}: "
                                f"{error.get('message', 'unknown sidecar error')}"
                            )
                        )
                    else:
                        future.set_result(message.get("result", {}))
                except Exception as exc:
                    self._fail_pending(NodeProtocolError(f"invalid sidecar response: {exc}"))
        finally:
            if self._process and self._process.returncode is None:
                await self._process.wait()
            code = self._process.returncode if self._process else "unknown"
            details = self.stderr[-1] if self.stderr else "no diagnostics"
            self._fail_pending(
                NodeProtocolError(f"sidecar exited with code {code}: {details}")
            )

    async def _read_stderr(self) -> None:
        assert self._process and self._process.stderr
        while line := await self._process.stderr.readline():
            text = line.decode(errors="replace").rstrip()
            if text:
                self.stderr.append(text)
                del self.stderr[:-100]

    def _fail_pending(self, error: Exception) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

    async def __aenter__(self) -> NodeSidecar:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
