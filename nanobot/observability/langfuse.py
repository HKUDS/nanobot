"""Process-start Langfuse configuration shared by provider construction paths."""

from __future__ import annotations

import importlib
import importlib.util
import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.observability.config import LangfuseConfig, resolve_langfuse_config

if TYPE_CHECKING:
    from nanobot.config.schema import Config

_MISSING_WARNING = (
    "Langfuse tracing is enabled but langfuse is not installed; "
    "run `nanobot plugins enable langfuse` to enable tracing"
)


class LangfuseObservation:
    """Keep native tracing updates independent of model request success."""

    def __init__(self, generation: Any = None) -> None:
        self._generation = generation

    def update(self, **kwargs: Any) -> None:
        if self._generation is not None:
            try:
                self._generation.update(**kwargs)
            except Exception:
                logger.warning("Langfuse generation update failed; continuing without tracing")

    def end(self) -> None:
        if self._generation is not None:
            try:
                self._generation.end()
            except Exception:
                logger.warning("Langfuse generation close failed; continuing without tracing")


class LangfuseRuntime:
    """One immutable tracing decision per nanobot process; changes require restart."""

    def __init__(self, settings: LangfuseConfig) -> None:
        self._settings = settings.model_copy(deep=True)
        self.available = False
        self._client: Any = None  # Optional third-party SDK boundary.
        try:
            self.available = importlib.util.find_spec("langfuse") is not None
            if not settings.enabled:
                return
            if not self.available:
                logger.warning(_MISSING_WARNING)
                return
            if not settings.configured or not settings.base_url.strip():
                logger.warning("Langfuse tracing needs a base URL and both keys; tracing disabled")
                return
            from langfuse import Langfuse

            self._client = Langfuse(
                public_key=settings.public_key,
                secret_key=settings.secret_key,
                base_url=settings.base_url,
                tracing_enabled=True,
            )
        except Exception:
            # SDK diagnostics can include credentials. Never forward exception text.
            logger.warning("Langfuse initialization failed; continuing without tracing")

    @property
    def settings(self) -> LangfuseConfig:
        return self._settings.model_copy(deep=True)

    @property
    def active(self) -> bool:
        return self._client is not None

    def openai_options(self) -> dict[str, str]:
        """Use the SDK's public per-request project selector, not its default client."""
        if not self.active:
            return {}
        try:
            importlib.import_module("langfuse.openai")
        except Exception:
            logger.warning("Langfuse OpenAI instrumentation unavailable; continuing without tracing")
            return {}
        return {"langfuse_public_key": self._settings.public_key}

    def start_observation(self, **kwargs: Any) -> LangfuseObservation:
        generation = None
        if self._client is not None:
            try:
                generation = self._client.start_observation(**kwargs)
            except Exception:
                logger.warning("Langfuse observation failed; continuing without tracing")
        return LangfuseObservation(generation)

    def shutdown(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                client.shutdown()
            except Exception:
                logger.warning("Langfuse shutdown failed")


_running: LangfuseRuntime | None = None


@contextmanager
def langfuse_runtime_owner() -> Generator[None, None, None]:
    """Bind startup state and the SDK's process flag to a CLI/gateway/API lifetime."""
    global _running
    if _running is not None:
        raise RuntimeError("A Langfuse runtime is already active")
    previous_flag = os.environ.get("LANGFUSE_TRACING_ENABLED")
    try:
        yield
    finally:
        runtime, _running = _running, None
        if runtime is not None:
            runtime.shutdown()
        if previous_flag is None:
            os.environ.pop("LANGFUSE_TRACING_ENABLED", None)
        else:
            os.environ["LANGFUSE_TRACING_ENABLED"] = previous_flag


def initialize_langfuse(config: Config) -> LangfuseRuntime:
    """Freeze configuration before requests/settings; never called by WebUI mutations."""
    global _running
    if _running is None:
        settings = resolve_langfuse_config(config)
        # The public SDK ANDs its constructor flag with this environment flag,
        # including when the OpenAI wrapper reconstructs a client by public key.
        if config.observability.langfuse is not None:
            os.environ["LANGFUSE_TRACING_ENABLED"] = "true" if settings.enabled else "false"
        _running = LangfuseRuntime(settings)
        if config.observability.langfuse is not None and not _running.active:
            os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
    return _running


def get_running_langfuse_config() -> LangfuseConfig | None:
    return _running.settings if _running is not None else None


def get_running_langfuse_available() -> bool | None:
    return _running.available if _running is not None else None


def get_running_langfuse_active() -> bool | None:
    return _running.active if _running is not None else None


def provider_langfuse_runtime(config: Config | None = None) -> LangfuseRuntime:
    """Composition entrypoints own the process snapshot; direct providers retain env setup."""
    return _running if _running is not None else LangfuseRuntime(resolve_langfuse_config(config))
