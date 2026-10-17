"""Gateway-owned state for the WebUI settings surface."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from filelock import FileLock

from nanobot.config.loader import config_persistence_data, load_config, save_config
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
            return self._read()

    def _read(self) -> Config:
        return load_config(self.path)

    def _write(self, config: Config) -> None:
        save_config(config, self.path)

    def update(
        self,
        mutation: Callable[[Config], _T],
        *,
        on_save_error: Callable[[_T], None] | None = None,
        on_commit: Callable[[_T], None] | None = None,
    ) -> _T:
        """Apply and atomically persist one path-scoped read-modify-write operation."""
        with self._lock, self._file_lock:
            config = self._read()
            before = config_persistence_data(config)
            result = mutation(config)
            try:
                if config_persistence_data(config) != before:
                    self._write(config)
            except BaseException:
                if on_save_error is not None:
                    on_save_error(result)
                raise
            if on_commit is not None:
                on_commit(result)
            return result


class WebUIOAuthFlowRegistry:
    """Bounded, thread-safe OAuth flows owned by one gateway instance."""

    def __init__(self, *, max_flows: int = _WEBUI_OAUTH_MAX_FLOWS) -> None:
        if max_flows < 1:
            raise ValueError("max_flows must be at least one")
        self._max_flows = max_flows
        self._flows: dict[str, tuple[str, Any]] = {}
        self._lock = threading.Lock()

    def register(self, provider_name: str, flow_id: str, flow: Any) -> None:
        discarded: list[Any] = []
        with self._lock:
            for existing_id, (_provider_name, existing) in list(self._flows.items()):
                if existing.expired:
                    discarded.append(self._flows.pop(existing_id)[1])
            while len(self._flows) >= self._max_flows:
                oldest_id = next(iter(self._flows))
                discarded.append(self._flows.pop(oldest_id)[1])
            self._flows[flow_id] = (provider_name, flow)
        for existing in discarded:
            existing.cancel()

    def get(self, provider_name: str, flow_id: str) -> Any | None:
        with self._lock:
            registered = self._flows.get(flow_id)
            if registered is None or registered[0] != provider_name:
                return None
            flow = registered[1]
            if not flow.expired:
                return flow
            self._flows.pop(flow_id, None)
        flow.cancel()
        return None

    def remove(
        self,
        provider_name: str,
        flow_id: str,
        flow: Any,
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
                self._flows.pop(flow_id)
        if cancel:
            flow.cancel()

    def clear(self, provider_name: str) -> None:
        with self._lock:
            flow_ids = [
                flow_id
                for flow_id, (registered_provider, _flow) in self._flows.items()
                if registered_provider == provider_name
            ]
            flows = [self._flows.pop(flow_id)[1] for flow_id in flow_ids]
        for flow in flows:
            flow.cancel()


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
