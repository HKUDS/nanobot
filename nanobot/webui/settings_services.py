"""Gateway-owned state for the WebUI settings surface."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config

_T = TypeVar("_T")
_WEBUI_OAUTH_MAX_FLOWS = 8


class WebUISettingsConfig:
    """Instance-scoped config access with serialized read-modify-write operations."""

    def __init__(self, config_path: Path) -> None:
        self.path = config_path.expanduser().resolve(strict=False)
        self._lock = threading.RLock()

    def load(self) -> Config:
        """Load this gateway's config without consulting the process-global path."""
        with self._lock:
            return load_config(self.path)

    def update(self, mutation: Callable[[Config], _T]) -> _T:
        """Apply and atomically persist one in-process read-modify-write operation."""
        with self._lock:
            config = load_config(self.path)
            result = mutation(config)
            save_config(config, self.path)
            return result

    def run_serialized(self, operation: Callable[[Path], _T]) -> _T:
        """Run a path-aware read-modify-write operation under the instance lock."""
        with self._lock:
            return operation(self.path)


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

    @classmethod
    def create(cls, config_path: Path) -> WebUISettingsServices:
        return cls(
            config=WebUISettingsConfig(config_path),
            oauth_flows=WebUIOAuthFlowRegistry(),
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
