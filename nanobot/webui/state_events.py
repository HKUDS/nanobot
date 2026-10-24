"""Gateway-scoped invalidation for the WebUI's fixed non-session resources."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger
from watchfiles import awatch  # pyright: ignore[reportUnknownVariableType]

from nanobot.llm_usage.service import llm_usage_store_path
from nanobot.llm_usage.store import LLMUsageChangeSource
from nanobot.pairing.store import pairing_store_path, pending_expirations
from nanobot.webui.settings_services import WebUISettingsConfig

if TYPE_CHECKING:
    from nanobot.cron.service import CronService
    from nanobot.triggers.local_store import LocalTriggerStore
    from nanobot.webui.remote_instances import RemoteInstances

WebUIStateResource = Literal["pairing", "channels", "automations", "usage", "remote_instances"]
WEBUI_STATE_RESOURCES: tuple[WebUIStateResource, ...] = (
    "pairing", "channels", "automations", "usage", "remote_instances",
)
StateEventSender = Callable[[tuple[WebUIStateResource, ...]], Awaitable[None]]
_CHANNEL_SAMPLE_INTERVAL_S = 1.0
_CLOCK_RECHECK_INTERVAL_S = 60.0
_COALESCE_INTERVAL_S = 0.05
_T = TypeVar("_T")


def _usage_zone(name: str | None) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(name) if name else timezone.utc
    except ZoneInfoNotFoundError:
        return timezone.utc


class WebUIStateEvents:
    """Own filesystem watches, bounded runtime sampling, and deadline notifications.

    Persisted changes never reload a live domain owner here: existing read paths
    retain their own locking, action merging, and active-execution protections.
    """

    def __init__(
        self,
        settings: WebUISettingsConfig,
        *,
        remote_instances: RemoteInstances | None = None,
        cron_service: CronService | None = None,
        local_trigger_store: LocalTriggerStore | None = None,
        channel_runtime_status: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._settings = settings
        self._pairing_path = pairing_store_path().resolve(strict=False)
        self._usage_path = llm_usage_store_path().resolve(strict=False)
        self._usage_wal_path = self._usage_path.with_name(self._usage_path.name + "-wal")
        self._remote_path = remote_instances.path.resolve(strict=False) if remote_instances is not None else None
        self._remote_pairing_root = remote_instances.pairing.root.resolve(strict=False) if remote_instances is not None else None
        self._file_roots = tuple(dict.fromkeys((
            settings.path.parent, self._pairing_path.parent, self._usage_path.parent,
            *((self._remote_path.parent,) if self._remote_path is not None else ()),
        )))
        self._automation_roots = tuple(dict.fromkeys(
            root.resolve(strict=False)
            for root in (
                *((cron_service.store_path.parent,) if cron_service is not None else ()),
                *((local_trigger_store.root,) if local_trigger_store is not None else ()),
            )
        ))
        self._automation_directories = frozenset(
            path.resolve(strict=False)
            for path in (
                *self._automation_roots,
                *((cron_service.store_path.parent / "runs",) if cron_service is not None else ()),
                *((local_trigger_store.inbox_dir, local_trigger_store.processing_dir,
                   local_trigger_store.failed_dir, local_trigger_store.runs_dir)
                  if local_trigger_store is not None else ()),
            )
        )
        self._recursive_roots = tuple(dict.fromkeys((
            *self._automation_roots,
            *((self._remote_pairing_root,) if self._remote_pairing_root is not None else ()),
        )))
        self._channel_runtime_status = channel_runtime_status
        self._lifecycle_lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sender: StateEventSender | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._watch_stop = asyncio.Event()
        self._dirty = asyncio.Event()
        self._clock_changed = asyncio.Event()
        self._pending: set[WebUIStateResource] = set()
        self._expirations: tuple[float, ...] = ()
        self._usage_timezone: str | None = None
        self._usage_changes = LLMUsageChangeSource(self._usage_path)

    async def start(self, sender: StateEventSender) -> None:
        """Start once per channel lifetime; no task is created by construction."""
        async with self._lifecycle_lock:
            if self._loop is not None:
                return
            self._watch_stop = asyncio.Event()
            self._dirty = asyncio.Event()
            self._clock_changed = asyncio.Event()
            self._pending.clear()
            self._sender = sender
            self._loop = asyncio.get_running_loop()
            try:
                # Watch parents, rather than file inodes, to observe atomic replacement
                # and first creation. Automation and remote pairing roots need recursive watching.
                ready: list[asyncio.Event] = []
                for roots, recursive in ((self._file_roots, False), (self._recursive_roots, True)):
                    for root in roots:
                        registered = asyncio.Event()
                        ready.append(registered)
                        self._tasks.append(asyncio.create_task(
                            self._watch_persistence(root, recursive=recursive, registered=registered),
                            name="webui-state-files",
                        ))
                await self._wait_for_watches(ready)
                await self._read_pairing_deadlines()
                await self._read_usage_timezone(initial=True)
                try:
                    await self._read_source(self._usage_changes.changed)
                except (OSError, sqlite3.Error):
                    logger.warning("Could not inspect initial LLM usage revision")
                self._tasks.extend((
                    asyncio.create_task(self._emit_changes(), name="webui-state-delivery"),
                    asyncio.create_task(self._watch_clock(), name="webui-state-clock"),
                ))
                if self._channel_runtime_status is not None:
                    self._tasks.append(asyncio.create_task(
                        self._sample_channel_runtime(self._channel_snapshot()),
                        name="webui-state-channel-runtime",
                    ))
                for task in self._tasks:
                    task.add_done_callback(self._source_finished)
            except BaseException:
                await self._close_sources()
                raise

    async def _wait_for_watches(self, ready: list[asyncio.Event]) -> None:
        registration = asyncio.gather(*(event.wait() for event in ready))
        try:
            done, _pending = await asyncio.wait(
                (*self._tasks, registration), return_when=asyncio.FIRST_COMPLETED,
            )
            for task in self._tasks:
                if task in done:
                    task.result()
                    raise RuntimeError("WebUI state watch stopped before registration")
            await registration
        finally:
            registration.cancel()
            await asyncio.gather(registration, return_exceptions=True)

    @staticmethod
    def _source_finished(task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.opt(exception=error).error("WebUI state source stopped: {}", task.get_name())

    def notify(self, *resources: WebUIStateResource) -> None:
        """Invalidate fixed resources, including from a domain worker thread."""
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._enqueue, self._watch_stop, resources)
        except RuntimeError:
            # A worker finishing after the owning event loop closed cannot deliver.
            if not loop.is_closed():
                raise

    def _enqueue(
        self, lifetime: asyncio.Event, resources: tuple[WebUIStateResource, ...],
    ) -> None:
        if lifetime is not self._watch_stop or self._loop is None:
            return
        self._pending.update(resources)
        self._dirty.set()

    async def close(self) -> None:
        """Join every owned source and discard pending notifications before reuse."""
        async with self._lifecycle_lock:
            cleanup = asyncio.create_task(self._close_sources())
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise

    async def _close_sources(self) -> None:
        self._loop = None
        self._watch_stop.set()
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self._read_source(self._usage_changes.close)
        self._pending.clear()
        self._sender = None

    @staticmethod
    async def _read_source(operation: Callable[[], _T]) -> _T:
        worker = asyncio.create_task(asyncio.to_thread(operation))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            # asyncio.to_thread cancellation does not stop its thread. Keep the
            # source owned until its actual read exits before closing the lifetime.
            await asyncio.gather(worker, return_exceptions=True)
            raise

    async def _emit_changes(self) -> None:
        while True:
            await self._dirty.wait()
            self._dirty.clear()
            await asyncio.sleep(_COALESCE_INTERVAL_S)
            resources: tuple[WebUIStateResource, ...] = tuple(
                item for item in WEBUI_STATE_RESOURCES if item in self._pending
            )
            self._pending.clear()
            sender = self._sender
            if resources and sender is not None:
                try:
                    await sender(resources)
                except Exception:
                    logger.exception("Could not deliver WebUI state invalidation")

    def _persistent_resources(self, path: Path) -> tuple[WebUIStateResource, ...]:
        if path == self._settings.path:
            return ("channels",)
        if path == self._pairing_path:
            return ("pairing",)
        if path in (self._usage_path, self._usage_wal_path):
            return ("usage",)
        if path == self._remote_path or (
            self._remote_pairing_root is not None and path.is_relative_to(self._remote_pairing_root)
        ):
            return ("remote_instances",)
        # A new directory may be the only signal for its first published child.
        # Only known data directories qualify; locks and atomic staging files do not.
        if path in self._automation_directories or (
            path.suffix in {".json", ".jsonl"}
            and any(path.is_relative_to(root) for root in self._automation_roots)
        ):
            return ("automations",)
        return ()

    def _watch_path(self, path: Path, *, recursive: bool) -> bool:
        resources = self._persistent_resources(path)
        nested = "automations" in resources or (
            self._remote_pairing_root is not None and path.is_relative_to(self._remote_pairing_root)
        )
        return bool(resources) and (nested == recursive)

    async def _watch_persistence(
        self, root: Path, *, recursive: bool, registered: asyncio.Event,
    ) -> None:
        recovering = False
        while True:
            try:
                root.mkdir(parents=True, exist_ok=True, mode=0o700 if root == self._remote_pairing_root else 0o777)
                async for changes in awatch(
                    root,
                    recursive=recursive,
                    watch_filter=None,
                    debounce=100,
                    step=25,
                    rust_timeout=250,
                    yield_on_timeout=True,
                    # WSL's default mtime-only polling can miss same-second atomic
                    # replacements; use the native notification backend instead.
                    force_polling=False,
                    stop_event=self._watch_stop,
                ):
                    # An unfiltered yield confirms native registration. Business
                    # filtering must not hide readiness in a continuously busy root.
                    registered.set()
                    if recovering:
                        recovering = False
                        # Reconcile cached deadlines only after the replacement
                        # watch is registered, so changes in the gap are not lost.
                        if recursive:
                            if any(item.is_relative_to(root) for item in self._automation_roots):
                                self.notify("automations")
                            if self._remote_pairing_root is not None and self._remote_pairing_root.is_relative_to(root):
                                self.notify("remote_instances")
                        else:
                            await self._persistent_changes({
                                path for path in (self._settings.path, self._pairing_path, self._usage_path, self._remote_path)
                                if path is not None and path.parent == root
                            })
                    paths = {Path(path) for _change, path in changes}
                    paths = {path for path in paths if self._watch_path(path, recursive=recursive)}
                    if paths:
                        await self._persistent_changes(paths)
                return
            except (OSError, RuntimeError, ExceptionGroup) as error:
                # awatch wraps native read failures in AnyIO's task group. Retry
                # only supported I/O failures; other grouped errors must surface.
                if isinstance(error, ExceptionGroup) and error.split((OSError, RuntimeError))[1] is not None:
                    raise
                if not registered.is_set():
                    raise
                logger.exception("WebUI persistence watch interrupted; re-registering {}", root)
                recovering = True
                await asyncio.sleep(1.0)

    async def _persistent_changes(self, paths: set[Path]) -> None:
        resources: set[WebUIStateResource] = set()
        for path in paths:
            resources.update(self._persistent_resources(path))
        if "pairing" in resources:
            await self._read_pairing_deadlines()
        if self._settings.path in paths:
            await self._read_usage_timezone()
        if "usage" in resources:
            try:
                if not await self._read_source(self._usage_changes.changed):
                    resources.discard("usage")
            except (OSError, sqlite3.Error):
                # The read API owns error reporting; a temporarily busy store
                # must still invalidate an already displayed chart.
                logger.warning("Could not inspect committed LLM usage revision")
        if resources:
            self.notify(*resources)

    async def _read_pairing_deadlines(self) -> None:
        try:
            self._expirations = await self._read_source(lambda: pending_expirations(self._pairing_path))
        except (OSError, UnicodeDecodeError):
            logger.warning("Could not read pairing expiration deadlines")
        self._clock_changed.set()

    async def _read_usage_timezone(self, *, initial: bool = False) -> None:
        try:
            config = await self._read_source(self._settings.load)
        except (OSError, ValueError):
            logger.warning("Could not read WebUI usage timezone")
            return
        timezone_name = config.agents.defaults.timezone
        if timezone_name != self._usage_timezone:
            self._usage_timezone = timezone_name
            self._clock_changed.set()
            if not initial:
                self.notify("usage")

    async def _watch_clock(self) -> None:
        previous_day = datetime.fromtimestamp(time.time(), _usage_zone(self._usage_timezone)).date()
        while True:
            self._clock_changed.clear()
            now = time.time()
            expired = tuple(deadline for deadline in self._expirations if deadline < now)
            if expired:
                self._expirations = tuple(deadline for deadline in self._expirations if deadline >= now)
                self.notify("pairing")
            local_now = datetime.fromtimestamp(now, _usage_zone(self._usage_timezone))
            if local_now.date() != previous_day:
                previous_day = local_now.date()
                self.notify("usage")
            tomorrow = local_now.date() + timedelta(days=1)
            next_day = datetime.combine(tomorrow, datetime.min.time(), tzinfo=local_now.tzinfo)
            deadlines = (next_day.timestamp(), *self._expirations)
            delay = min(_CLOCK_RECHECK_INTERVAL_S, max(0.01, min(deadlines) - now + 0.01))
            try:
                await asyncio.wait_for(self._clock_changed.wait(), timeout=delay)
            except TimeoutError:
                pass

    def _channel_snapshot(self) -> tuple[tuple[object, ...], ...]:
        assert self._channel_runtime_status is not None
        return tuple(
            (name, *(status.get(field) for field in (
                "enabled", "running", "state", "owner", "instance_id", "error",
            )))
            for name, status in sorted(self._channel_runtime_status().items())
        )

    async def _sample_channel_runtime(self, previous: tuple[tuple[object, ...], ...]) -> None:
        # This samples only the manager's small in-memory status map. It never
        # reads config, plugin metadata, pairing requests, jobs, or usage payloads.
        while True:
            await asyncio.sleep(_CHANNEL_SAMPLE_INTERVAL_S)
            try:
                current = self._channel_snapshot()
            except Exception:
                logger.exception("Could not sample channel runtime status")
                continue
            if current != previous:
                previous = current
                self.notify("channels")
