"""Keep an explicitly requested update alive across browser reconnects."""

from __future__ import annotations

import asyncio
from typing import Literal, TypedDict

from nanobot.update import UpdateError, update_installation


class UpdateStatus(TypedDict):
    state: Literal["idle", "running", "succeeded", "failed"]
    mode: Literal["release", "dev"]
    message: str
    version: str | None
    requires_restart: bool


class UpdateService:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._status: UpdateStatus = {
            "state": "idle", "mode": "release", "message": "",
            "version": None, "requires_restart": False,
        }

    def status(self) -> UpdateStatus:
        return self._status.copy()

    def start(self, *, dev: bool) -> UpdateStatus:
        if self._task is not None and not self._task.done():
            raise UpdateError("A nanobot update is already running.")
        self._status = {
            "state": "running", "mode": "dev" if dev else "release",
            "message": "Preparing update…", "version": None, "requires_restart": False,
        }
        self._task = asyncio.create_task(self._execute(dev), name="nanobot-update")
        return self.status()

    async def _execute(self, dev: bool) -> None:
        loop = asyncio.get_running_loop()

        def progress(message: str) -> None:
            loop.call_soon_threadsafe(self._progress, message)

        try:
            result = await asyncio.to_thread(update_installation, dev=dev, output=progress)
        except Exception as exc:
            self._status.update(state="failed", message=str(exc))
        else:
            self._status.update(
                state="succeeded", version=result["version"], requires_restart=True,
                message="Update installed. Restart nanobot to apply it.",
            )

    def _progress(self, message: str) -> None:
        if self._status["state"] == "running":
            self._status["message"] = message

    async def close(self) -> None:
        if self._task is not None:
            await asyncio.shield(self._task)
