from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeVar

from filelock import FileLock

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config

_T = TypeVar("_T")
_WEBUI_OAUTH_MAX_FLOWS = 8


class WebUISettingsConfig:
    """Path-scoped config access with process-safe read-modify-write operations."""

    def __init__(self, config_path: Path) -> None:
        self.path = config_path.expanduser().resolve(strict=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")
        self._file_lock = FileLock(str(lock_path))

    def load(self) -> Config:
        """Load this gateway's config without consulting the process-global path."""
        with self._lock:
            return load_config(self.path)

    def update(self, mutation: Callable[[Config], _T]) -> _T:
        """Apply and atomically persist one path-scoped read-modify-write operation."""
        with self._lock, self._file_lock:
            config = load_config(self.path)
            result = mutation(config)
            save_config(config, self.path)
            return result

    def run_serialized(self, operation: Callable[[Path], _T]) -> _T:
        """Run a path-aware read-modify-write operation under the config-file lock."""
        with self._lock, self._file_lock:
            return operation(self.path)


class WebUIOAuthToken(Protocol):
    @property
    def access(self) -> str: ...


class WebUIOAuthFlow(Protocol):
    """Provider flow whose cancellation and actual worker exit are separate."""

    @property
    def expired(self) -> bool: ...

    @property
    def has_pending_work(self) -> bool:
        """A nonblocking observation of live workers, including cleanup."""
        ...

    def complete(self, response: str | None = None, /) -> WebUIOAuthToken | None: ...
    def cancel(self) -> None: ...
    def wait_closed(self) -> None:
        """Return only after the cancelled flow's workers have actually exited."""
        ...


class WebUIOAuthFlowRegistry:
    """Bounded, thread-safe OAuth ownership, including removed flows still stopping."""

    def __init__(self, *, max_flows: int = _WEBUI_OAUTH_MAX_FLOWS) -> None:
        if max_flows < 1:
            raise ValueError("max_flows must be at least one")
        self._max_flows = max_flows
        self._flows: dict[str, tuple[str, WebUIOAuthFlow]] = {}
        self._retiring: dict[int, tuple[str, WebUIOAuthFlow]] = {}
        self._cancelling: set[int] = set()
        self._lock = threading.Lock()
        self._closed = False
        self._closing = False

    @property
    def has_pending_work(self) -> bool:
        with self._lock:
            return self._closing or bool(self._cancelling) or any(
                flow.has_pending_work
                for _provider, flow in (*self._flows.values(), *self._retiring.values())
            )

    def _retire_locked(self, flow_id: str, *, cancel: bool = True) -> WebUIOAuthFlow:
        registered = self._flows.pop(flow_id)
        self._retiring[id(registered[1])] = registered
        if cancel:
            self._cancelling.add(id(registered[1]))
        return registered[1]

    def _cancel(self, flow: WebUIOAuthFlow) -> None:
        flow.cancel()
        with self._lock:
            self._cancelling.discard(id(flow))

    def register(self, provider_name: str, flow_id: str, flow: WebUIOAuthFlow) -> None:
        """Register before start; reject capacity rather than losing a live worker."""
        discarded: list[WebUIOAuthFlow] = []
        with self._lock:
            if self._closed:
                raise RuntimeError("OAuth sign-in is closing. Reconnect before starting again.")
            for existing_id, (_provider_name, existing) in list(self._flows.items()):
                if existing.expired or existing_id == flow_id:
                    discarded.append(self._retire_locked(existing_id))
            if len(self._flows) >= self._max_flows:
                oldest_id = next(iter(self._flows))
                discarded.append(self._retire_locked(oldest_id))
        # Never hold the registry lock while a provider waits for its commit lock.
        for existing in discarded:
            self._cancel(existing)
        with self._lock:
            self._retiring = {
                key: value for key, value in self._retiring.items()
                if key in self._cancelling or value[1].has_pending_work
            }
            if self._closed:
                raise RuntimeError("OAuth sign-in is closing. Reconnect before starting again.")
            if len(self._flows) + len(self._retiring) >= self._max_flows:
                raise RuntimeError("Previous sign-ins are still stopping. Try again shortly.")
            self._flows[flow_id] = (provider_name, flow)

    def get(self, provider_name: str, flow_id: str) -> WebUIOAuthFlow | None:
        with self._lock:
            registered = self._flows.get(flow_id)
            if registered is None or registered[0] != provider_name:
                return None
            flow = registered[1]
            if not flow.expired:
                return flow
            self._retire_locked(flow_id)
        self._cancel(flow)
        return None

    def remove(
        self,
        provider_name: str,
        flow_id: str,
        flow: WebUIOAuthFlow,
        *,
        cancel: bool = True,
    ) -> None:
        with self._lock:
            registered = self._flows.get(flow_id)
            if (
                registered is not None
                and registered[0] == provider_name
                and registered[1] is flow
            ):
                self._retire_locked(flow_id, cancel=cancel)
        if cancel:
            self._cancel(flow)

    def clear(self, provider_name: str) -> None:
        with self._lock:
            flow_ids = [
                flow_id
                for flow_id, (registered_provider, _flow) in self._flows.items()
                if registered_provider == provider_name
            ]
            for flow_id in flow_ids:
                self._retire_locked(flow_id)
            flows = [
                flow for provider, flow in self._retiring.values() if provider == provider_name
            ]
        for flow in flows:
            self._cancel(flow)

    def close(self) -> None:
        """Cancel and join all owned workers; failure retains ownership for retry."""
        with self._lock:
            self._closed = True
            self._closing = True
            for flow_id in tuple(self._flows):
                self._retire_locked(flow_id)
            flows = [flow for _provider, flow in self._retiring.values()]
        for flow in flows:
            self._cancel(flow)
        for flow in flows:
            flow.wait_closed()
        with self._lock:
            self._retiring.clear()
            self._closing = False


@dataclass(frozen=True)
class WebUISettingsServices:
    """Settings dependencies composed once for a gateway instance."""

    config: WebUISettingsConfig
    oauth_flows: WebUIOAuthFlowRegistry
    rename_model_preset: Callable[[str, str], int] | None = None
    refresh_runtime_config: Callable[[], None] | None = None

    @classmethod
    def create(
        cls,
        config_path: Path,
        *,
        rename_model_preset: Callable[[str, str], int] | None = None,
        refresh_runtime_config: Callable[[], None] | None = None,
    ) -> WebUISettingsServices:
        return cls(
            config=WebUISettingsConfig(config_path),
            oauth_flows=WebUIOAuthFlowRegistry(),
            rename_model_preset=rename_model_preset,
            refresh_runtime_config=refresh_runtime_config,
        )

    def read(
        self,
        operation: Callable[..., _T],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> _T:
        """Run a settings read against this gateway's explicit config path."""
        return operation(*args, config_path=self.config.path, **kwargs)

    def mutate(
        self,
        operation: Callable[..., _T],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> _T:
        """Serialize a path-aware settings read-modify-write operation."""
        return self.config.run_serialized(
            lambda config_path: operation(
                *args,
                config_path=config_path,
                **kwargs,
            )
        )
