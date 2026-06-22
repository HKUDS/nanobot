"""Runtime helpers for SDK calls."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.providers.factory import ProviderSnapshot, build_provider_snapshot

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop


def ensure_single_model_selector(
    *,
    model: str | None,
    model_preset: str | None,
) -> None:
    if model is not None and model_preset is not None:
        raise ValueError("model and model_preset are mutually exclusive")


def build_process_direct_kwargs(
    *,
    session_key: str,
    channel: str,
    chat_id: str,
    sender_id: str,
    media: list[str] | None,
    ephemeral: bool,
    on_stream: Any | None = None,
    on_stream_end: Any | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"session_key": session_key}
    if channel != "cli":
        kwargs["channel"] = channel
    if chat_id != "direct":
        kwargs["chat_id"] = chat_id
    if sender_id != "user":
        kwargs["sender_id"] = sender_id
    if media is not None:
        kwargs["media"] = media
    if ephemeral:
        kwargs["ephemeral"] = True
        kwargs["_run_extra_hooks_for_ephemeral"] = True
    if on_stream is not None:
        kwargs["on_stream"] = on_stream
    if on_stream_end is not None:
        kwargs["on_stream_end"] = on_stream_end
    return kwargs


class SDKRuntimeGate:
    """Allow normal SDK runs to overlap while model overrides stay exclusive."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._readers = 0
        self._writer_active = False
        self._writers_waiting = 0

    def slot(self, *, exclusive: bool) -> SDKRuntimeGateSlot:
        return SDKRuntimeGateSlot(self, exclusive=exclusive)

    async def _acquire(self, *, exclusive: bool) -> None:
        async with self._condition:
            if exclusive:
                self._writers_waiting += 1
                try:
                    await self._condition.wait_for(
                        lambda: not self._writer_active and self._readers == 0
                    )
                    self._writer_active = True
                finally:
                    self._writers_waiting -= 1
                    self._condition.notify_all()
                return

            await self._condition.wait_for(
                lambda: not self._writer_active and self._writers_waiting == 0
            )
            self._readers += 1

    async def _release(self, *, exclusive: bool) -> None:
        async with self._condition:
            if exclusive:
                self._writer_active = False
            else:
                self._readers = max(0, self._readers - 1)
            self._condition.notify_all()


class SDKRuntimeGateSlot:
    def __init__(self, gate: SDKRuntimeGate, *, exclusive: bool) -> None:
        self._gate = gate
        self._exclusive = exclusive

    async def __aenter__(self) -> None:
        await self._gate._acquire(exclusive=self._exclusive)

    async def __aexit__(self, *exc: object) -> None:
        await self._gate._release(exclusive=self._exclusive)


class SDKRuntimeController:
    """Apply per-run SDK model overrides without leaking global runtime state."""

    def __init__(self, loop: AgentLoop, *, config: Config | None = None) -> None:
        self._loop = loop
        self._config = config
        self._gate = SDKRuntimeGate()

    @asynccontextmanager
    async def override(
        self,
        *,
        model: str | None,
        model_preset: str | None,
    ) -> AsyncIterator[None]:
        ensure_single_model_selector(model=model, model_preset=model_preset)
        exclusive = model is not None or model_preset is not None
        async with self._gate.slot(exclusive=exclusive):
            override = self.model_override_snapshot(model=model, model_preset=model_preset)
            restore = self._current_snapshot() if override is not None else None
            restore_signature = self._loop._provider_signature
            if override is not None:
                self._loop._apply_provider_snapshot(
                    override,
                    publish_update=False,
                    model_preset=model_preset,
                )
            try:
                yield
            finally:
                if restore is not None:
                    self._restore_snapshot(
                        restore,
                        provider_signature=restore_signature,
                    )

    def model_override_snapshot(
        self,
        *,
        model: str | None,
        model_preset: str | None,
    ) -> ProviderSnapshot | None:
        ensure_single_model_selector(model=model, model_preset=model_preset)
        if model_preset is not None:
            return self._loop._build_model_preset_snapshot(model_preset)
        if model is None:
            return None

        if self._config is not None:
            base = self._config.resolve_preset(self._loop.model_preset)
            preset = base.model_copy(update={"model": model, "provider": "auto"})
            return build_provider_snapshot(self._config, preset=preset)

        generation = getattr(self._loop.provider, "generation", None)
        preset = ModelPresetConfig(
            model=model,
            provider="auto",
            max_tokens=getattr(generation, "max_tokens", 8192),
            context_window_tokens=self._loop.context_window_tokens,
            temperature=getattr(generation, "temperature", 0.1),
            reasoning_effort=getattr(generation, "reasoning_effort", None),
        )
        from nanobot.agent.model_presets import build_static_preset_snapshot

        return build_static_preset_snapshot(self._loop.provider, "sdk:override", preset)

    def _current_snapshot(self) -> ProviderSnapshot:
        signature = self._loop._provider_signature
        if signature is None:
            signature = ("sdk:runtime", id(self._loop.provider), self._loop.model)
        return ProviderSnapshot(
            provider=self._loop.provider,
            model=self._loop.model,
            context_window_tokens=self._loop.context_window_tokens,
            signature=signature,
        )

    def _restore_snapshot(
        self,
        snapshot: ProviderSnapshot,
        *,
        provider_signature: tuple[object, ...] | None,
    ) -> None:
        self._loop._apply_provider_snapshot(snapshot, publish_update=False)
        self._loop._provider_signature = provider_signature
