"""An owned OpenSSH master, never a user's shared control socket."""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
from pathlib import Path


class SSHMaster:
    """One authenticated transport per pinned connection, reaped on pause."""

    def __init__(self, args: list[str], host: str) -> None:
        self.args = args
        self.host = host
        self._directory: tempfile.TemporaryDirectory[str] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._stderr: asyncio.Task[None] | None = None
        self._error = bytearray()
        self._lock = asyncio.Lock()

    async def arguments(self, channel: list[str]) -> list[str]:
        from nanobot.webui.remote_ssh import RemoteError, ssh_error

        async with self._lock:
            if self._process is None or self._process.returncode is not None:
                await self.close()
                self._directory = tempfile.TemporaryDirectory(prefix="nb-ssh-")
                path = str(Path(self._directory.name) / "s")
                # Unix-domain socket paths have a small platform-dependent limit.
                if len(path.encode()) >= 100:
                    await self.close()
                    return channel
                self._error.clear()
                args = [self.args[0], "-o", "ControlMaster=yes", "-o", f"ControlPath={path}",
                        "-o", "ControlPersist=no", *self.args[1:], "-N", self.host]
                spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                    *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                ))
                try:
                    self._process = await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    self._process = await spawn
                    await self.close()
                    raise
                except BaseException:
                    await self.close()
                    raise
                process = self._process
                assert process is not None

                async def errors() -> None:
                    assert process.stderr is not None
                    while chunk := await process.stderr.read(4096):
                        self._error.extend(chunk[:max(0, 8192 - len(self._error))])

                self._stderr = asyncio.create_task(errors())
                try:
                    async with asyncio.timeout(20):
                        while not Path(path).exists():
                            if process.returncode is not None:
                                await self._stderr
                                raise RemoteError(ssh_error(bytes(self._error)))
                            await asyncio.sleep(0.02)
                except TimeoutError:
                    await self.close()
                    raise RemoteError("ssh_unreachable") from None
                except BaseException:
                    await self.close()
                    raise
            assert self._directory is not None
            # OpenSSH uses the first occurrence. Our private path overrides the
            # explicit no-sharing defaults, not host/agent/forwarding safeguards.
            return [channel[0], "-S", str(Path(self._directory.name) / "s"), *channel[1:]]

    async def close(self) -> None:
        from nanobot.webui.remote_ssh import stop_process

        if self._process is not None:
            await stop_process(self._process)
            self._process = None
        if self._stderr is not None:
            self._stderr.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stderr
            self._stderr = None
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None
