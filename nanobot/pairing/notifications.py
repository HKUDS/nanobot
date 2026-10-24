"""Payload-free notifications for changes to the authoritative pairing store."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import aclosing

from loguru import logger
from watchfiles import awatch  # pyright: ignore[reportUnknownVariableType]

from nanobot.pairing.store import pairing_store_path, pending_expirations


class PairingNotifications:
    """Watch one store's parent and schedule its pending-request expirations.

    Watching the parent, not the file inode, covers first creation and atomic
    replacement by this gateway or another process. Reads never persist GC.
    """

    def __init__(self) -> None:
        self._path = pairing_store_path().resolve(strict=False)
        self._lifecycle_lock = asyncio.Lock()
        self._sender: Callable[[], Awaitable[None]] | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._stop = asyncio.Event()
        self._changed = asyncio.Event()
        self._clock_changed = asyncio.Event()
        self._expirations: tuple[float, ...] = ()

    async def start(self, sender: Callable[[], Awaitable[None]]) -> None:
        """Register the native listener before the gateway accepts clients."""
        async with self._lifecycle_lock:
            if self._sender is not None:
                return
            self._sender = sender
            self._stop = asyncio.Event()
            self._changed = asyncio.Event()
            self._clock_changed = asyncio.Event()
            self._expirations = ()
            registered = asyncio.Event()
            watch = asyncio.create_task(self._watch(registered), name="pairing-files")
            self._tasks = [watch]
            ready = asyncio.create_task(registered.wait())
            try:
                done, _pending = await asyncio.wait((watch, ready), return_when=asyncio.FIRST_COMPLETED)
                if watch in done:
                    watch.result()
                    raise RuntimeError("Pairing watch stopped before registration")
                self._tasks.extend((
                    asyncio.create_task(self._watch_expirations(), name="pairing-expirations"),
                    asyncio.create_task(self._emit_changes(), name="pairing-delivery"),
                ))
                for task in self._tasks:
                    task.add_done_callback(self._source_finished)
            except BaseException:
                await self._close_sources()
                raise
            finally:
                ready.cancel()
                await asyncio.gather(ready, return_exceptions=True)

    @staticmethod
    def _source_finished(task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.opt(exception=error).error("Pairing notification source stopped: {}", task.get_name())

    async def close(self) -> None:
        """Join the native listener, timer, delivery and any in-flight read."""
        async with self._lifecycle_lock:
            cleanup = asyncio.create_task(self._close_sources())
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise

    async def _close_sources(self) -> None:
        self._stop.set()
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._sender = None
        self._changed.clear()
        self._expirations = ()

    async def _read_deadlines(self) -> None:
        worker = asyncio.create_task(
            asyncio.to_thread(pending_expirations, self._path), name="pairing-read",
        )
        try:
            self._expirations = await asyncio.shield(worker)
        except asyncio.CancelledError:
            # Cancelling to_thread does not stop its thread. Retain ownership
            # until the domain-lock-protected read actually finishes.
            await asyncio.gather(worker, return_exceptions=True)
            raise
        except (OSError, UnicodeDecodeError):
            logger.warning("Could not read pairing expiration deadlines")
        self._clock_changed.set()

    async def _watch(self, registered: asyncio.Event) -> None:
        recovering = False
        while True:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            async with aclosing(awatch(
                self._path.parent,
                recursive=False,
                watch_filter=None,
                debounce=100,
                step=25,
                rust_timeout=250,
                yield_on_timeout=True,
                # WSL's default mtime-only polling misses same-second replaces.
                force_polling=False,
                stop_event=self._stop,
            )) as changes:
                while True:
                    try:
                        batch = await anext(changes)
                    except StopAsyncIteration:
                        if self._stop.is_set():
                            return
                        raise RuntimeError("Pairing native watch stopped unexpectedly") from None
                    except (OSError, RuntimeError, ExceptionGroup) as error:
                        # Native failures can be wrapped by AnyIO. Only native
                        # I/O failures are recoverable; domain errors below are
                        # deliberately outside this handler.
                        if isinstance(error, ExceptionGroup) and error.split((OSError, RuntimeError))[1] is not None:
                            raise
                        if not registered.is_set():
                            raise
                        logger.opt(exception=error).warning("Pairing watch interrupted; re-registering")
                        recovering = True
                        break
                    changed = any(path == str(self._path) for _change, path in batch)
                    if changed or recovering or not registered.is_set():
                        await self._read_deadlines()
                    # Unfiltered yields confirm native registration even while
                    # unrelated sibling files are continuously being written.
                    registered.set()
                    if changed or recovering:
                        self._changed.set()
                    recovering = False
            await asyncio.sleep(1.0)

    async def _watch_expirations(self) -> None:
        while True:
            self._clock_changed.clear()
            now = time.time()
            if any(deadline < now for deadline in self._expirations):
                self._expirations = tuple(deadline for deadline in self._expirations if deadline >= now)
                self._changed.set()
            if not self._expirations:
                await self._clock_changed.wait()
                continue
            # Recheck wall time for clock jumps, without polling the store.
            delay = min(60.0, max(0.01, min(self._expirations) - now + 0.01))
            try:
                await asyncio.wait_for(self._clock_changed.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def _emit_changes(self) -> None:
        while True:
            await self._changed.wait()
            self._changed.clear()
            sender = self._sender
            if sender is not None:
                try:
                    await sender()
                except Exception:
                    logger.exception("Could not deliver pairing invalidation")
