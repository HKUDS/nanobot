"""Runtime model/provider coordination for the agent loop."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from nanobot.agent import model_presets as preset_helpers
from nanobot.providers.factory import ProviderSnapshot
from nanobot.utils.llm_runtime import LLMRuntime

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop


class RuntimeModelCoordinator:
    """Owns mutable provider/model state transitions for an AgentLoop."""

    def __init__(self, loop: AgentLoop) -> None:
        self._loop = loop

    def llm_runtime(self) -> LLMRuntime:
        """Return the current provider/model pair owned by the loop."""
        self.refresh_provider_snapshot()
        return LLMRuntime(self._loop.provider, self._loop.model)

    def sync_subagent_runtime_limits(self) -> None:
        """Keep subagent runtime limits aligned with mutable loop settings."""
        self._loop.subagents.max_iterations = self._loop.max_iterations

    def apply_provider_snapshot(
        self,
        snapshot: ProviderSnapshot,
        *,
        publish_update: bool = True,
        model_preset: str | None = None,
    ) -> None:
        """Swap model/provider for future turns without disturbing an active one."""
        loop = self._loop
        provider = snapshot.provider
        model = snapshot.model
        context_window_tokens = snapshot.context_window_tokens
        old_model = loop.model
        loop.provider = provider
        loop.model = model
        loop.context_window_tokens = context_window_tokens
        loop.runner.provider = provider
        loop.subagents.set_provider(provider, model)
        loop.consolidator.set_provider(provider, model, context_window_tokens)
        loop._provider_signature = snapshot.signature
        active_preset = model_preset if model_preset is not None else loop.model_preset
        if publish_update and loop._runtime_model_publisher is not None:
            loop._runtime_model_publisher(loop.model, active_preset)
        if publish_update:
            loop._runtime_events().runtime_model_changed(loop.model, active_preset)
        logger.info("Runtime model switched for next turn: {} -> {}", old_model, model)

    def refresh_provider_snapshot(self) -> None:
        """Refresh runtime provider state from the configured snapshot loader."""
        loop = self._loop
        if loop._provider_snapshot_loader is None:
            return
        try:
            snapshot = loop._provider_snapshot_loader()
        except Exception:
            logger.exception("Failed to refresh provider config")
            return
        default_selection = preset_helpers.default_selection_signature(snapshot.signature)
        if loop._active_preset and loop._default_selection_signature in (None, default_selection):
            loop._default_selection_signature = default_selection
            try:
                snapshot = self.build_model_preset_snapshot(loop._active_preset)
            except Exception:
                logger.exception("Failed to refresh active model preset")
                return
        else:
            loop._active_preset = None
            loop._default_selection_signature = default_selection
        if snapshot.signature == loop._provider_signature:
            return
        loop._default_selection_signature = preset_helpers.default_selection_signature(
            snapshot.signature
        )
        self.apply_provider_snapshot(snapshot)

    def build_model_preset_snapshot(self, name: str) -> ProviderSnapshot:
        """Resolve a preset into a provider snapshot."""
        loop = self._loop
        return preset_helpers.build_runtime_preset_snapshot(
            name=name,
            presets=loop.model_presets,
            provider=loop.provider,
            loader=loop._preset_snapshot_loader,
        )

    def set_model_preset(self, name: str | None, *, publish_update: bool = True) -> None:
        """Resolve a preset by name and apply all runtime model dependents."""
        loop = self._loop
        normalized = preset_helpers.normalize_preset_name(name, loop.model_presets)
        snapshot = self.build_model_preset_snapshot(normalized)
        self.apply_provider_snapshot(
            snapshot,
            publish_update=publish_update,
            model_preset=normalized,
        )
        loop._active_preset = normalized
