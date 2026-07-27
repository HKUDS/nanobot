"""Agent-side lifecycle for first-class extensions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.extensions.catalog import ExtensionCatalog, build_extension_catalog
from nanobot.extensions.registry import ExtensionDiagnostic
from nanobot.extensions.runtime import ActivationResult, ExtensionRuntimeManager

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop
    from nanobot.config.schema import Config


@dataclass(frozen=True, slots=True)
class ExtensionHostSnapshot:
    """Current discovery and activation result."""

    catalog: ExtensionCatalog
    activation: ActivationResult

    @property
    def diagnostics(self) -> tuple[ExtensionDiagnostic, ...]:
        return self.catalog.diagnostics + self.activation.diagnostics


class ExtensionHost:
    """Reload external extensions without coupling their lifecycle to AgentLoop."""

    def __init__(
        self,
        agent: AgentLoop,
        config_loader: Callable[[], Config],
        *,
        user_root: Path | None = None,
    ) -> None:
        self._agent = agent
        self._config_loader = config_loader
        self._user_root = user_root
        self._manager: ExtensionRuntimeManager | None = None
        self._snapshot: ExtensionHostSnapshot | None = None
        self._lock = asyncio.Lock()

    @property
    def snapshot(self) -> ExtensionHostSnapshot | None:
        return self._snapshot

    async def reload(self) -> ExtensionHostSnapshot:
        async with self._lock:
            await self._close_manager()
            self._snapshot = None
            config = self._config_loader()
            catalog = build_extension_catalog(
                config,
                user_root=self._user_root,
            )
            manager = ExtensionRuntimeManager(
                tools=self._agent.tools,
                commands=self._agent.commands,
                hook_factories=self._agent._hook_factories,
            )
            activation = await manager.activate(catalog.snapshot)
            self._manager = manager
            self._snapshot = ExtensionHostSnapshot(catalog, activation)
            for diagnostic in self._snapshot.diagnostics:
                logger.warning(
                    "Extension {} [{}]: {}",
                    diagnostic.extension_id,
                    diagnostic.code,
                    diagnostic.message,
                )
            return self._snapshot

    async def close(self) -> None:
        async with self._lock:
            await self._close_manager()
            self._snapshot = None

    async def _close_manager(self) -> None:
        if self._manager is not None:
            await self._manager.close()
            self._manager = None
