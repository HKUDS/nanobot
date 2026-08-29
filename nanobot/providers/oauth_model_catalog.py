"""Shared cache seam for OAuth provider model discovery."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from loguru import logger

from nanobot.providers.registry import ProviderModelSpec

CatalogSource = Literal["remote", "cache", "stale", "fallback"]


@dataclass(frozen=True, slots=True)
class OAuthModelCatalogSnapshot:
    """One usable catalog view, including where it came from."""

    models: tuple[ProviderModelSpec, ...]
    source: CatalogSource
    fetched_at: float
    message: str | None = None

    def find(self, model: str) -> ProviderModelSpec | None:
        wire_id = model.split("/", 1)[-1]
        return next(
            (item for item in self.models if item.id.split("/", 1)[-1] == wire_id),
            None,
        )


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    snapshot: OAuthModelCatalogSnapshot
    stored_at: float


class OAuthModelCatalog:
    """Cache one provider's discovery behind a small failure-tolerant interface."""

    def __init__(
        self,
        *,
        fallback_models: Sequence[ProviderModelSpec],
        fetch: Callable[[str | None], Sequence[ProviderModelSpec]],
        fresh_ttl_s: float = 5 * 60,
        stale_ttl_s: float = 24 * 60 * 60,
        failure_ttl_s: float = 30,
        max_entries: int = 8,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if fresh_ttl_s < 0 or stale_ttl_s < fresh_ttl_s or failure_ttl_s < 0:
            raise ValueError("catalog cache TTLs are invalid")
        if max_entries < 1:
            raise ValueError("catalog cache must allow at least one entry")
        self._fallback_models = tuple(fallback_models)
        self._fetch = fetch
        self._fresh_ttl_s = fresh_ttl_s
        self._stale_ttl_s = stale_ttl_s
        self._failure_ttl_s = failure_ttl_s
        self._max_entries = max_entries
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._condition = threading.Condition()
        self._entries: dict[str, _CacheEntry] = {}
        self._failures: dict[str, float] = {}
        self._inflight: set[str] = set()
        self._generation = 0

    def get(self, *, cache_key: str, proxy: str | None = None) -> OAuthModelCatalogSnapshot:
        """Return a fresh catalog, sharing concurrent work and retaining a fallback."""
        with self._condition:
            generation = self._generation
            cached = self._cached_result(cache_key)
            if cached is not None:
                return cached
            while cache_key in self._inflight:
                self._condition.wait()
                if generation != self._generation:
                    return self._stale_or_fallback(None, self._monotonic())
                cached = self._cached_result(cache_key)
                if cached is not None:
                    return cached
            self._inflight.add(cache_key)

        try:
            models = tuple(self._fetch(proxy))
            if not models:
                raise ValueError("provider returned an empty model catalog")
        except Exception as exc:
            logger.warning("OAuth model catalog refresh failed: type={}", type(exc).__name__)
            with self._condition:
                result = (
                    self._stale_or_fallback(None, self._monotonic())
                    if generation != self._generation
                    else self._failure_result(cache_key)
                )
        else:
            now = self._monotonic()
            result = OAuthModelCatalogSnapshot(
                models=models,
                source="remote",
                fetched_at=self._wall_clock(),
            )
            with self._condition:
                if generation != self._generation:
                    result = self._stale_or_fallback(None, now)
                else:
                    self._store(cache_key, _CacheEntry(snapshot=result, stored_at=now))
                    self._failures.pop(cache_key, None)
        finally:
            with self._condition:
                self._inflight.discard(cache_key)
                self._condition.notify_all()

        return result

    def invalidate(self) -> None:
        """Drop cached work and prevent an older identity refresh from being stored."""
        with self._condition:
            self._generation += 1
            self._entries.clear()
            self._failures.clear()
            self._condition.notify_all()

    def _cached_result(self, cache_key: str) -> OAuthModelCatalogSnapshot | None:
        now = self._monotonic()
        entry = self._entries.get(cache_key)
        if entry is not None and now - entry.stored_at < self._fresh_ttl_s:
            return replace(entry.snapshot, source="cache")
        failure_until = self._failures.get(cache_key)
        if failure_until is not None and failure_until <= now:
            self._failures.pop(cache_key, None)
        elif failure_until is not None:
            return self._stale_or_fallback(entry, now)
        return None

    def _failure_result(self, cache_key: str) -> OAuthModelCatalogSnapshot:
        now = self._monotonic()
        self._reserve(cache_key)
        self._failures[cache_key] = now + self._failure_ttl_s
        return self._stale_or_fallback(self._entries.get(cache_key), now)

    def _stale_or_fallback(
        self,
        entry: _CacheEntry | None,
        now: float,
    ) -> OAuthModelCatalogSnapshot:
        if entry is not None and now - entry.stored_at < self._stale_ttl_s:
            return replace(
                entry.snapshot,
                source="stale",
                message="Could not refresh the online model list; showing cached models.",
            )
        return OAuthModelCatalogSnapshot(
            models=self._fallback_models,
            source="fallback",
            fetched_at=self._wall_clock(),
            message="Could not load the online model list; showing built-in fallback models.",
        )

    def _store(self, cache_key: str, entry: _CacheEntry) -> None:
        self._reserve(cache_key)
        self._entries[cache_key] = entry

    def _reserve(self, cache_key: str) -> None:
        known = set(self._entries) | set(self._failures)
        if cache_key in known or len(known) < self._max_entries:
            return
        oldest = min(
            known,
            key=lambda key: (
                self._entries[key].stored_at
                if key in self._entries
                else self._failures[key] - self._failure_ttl_s
            ),
        )
        self._entries.pop(oldest, None)
        self._failures.pop(oldest, None)


def get_oauth_model_catalog(
    provider_name: str,
    *,
    proxy: str | None = None,
) -> OAuthModelCatalogSnapshot:
    """Discover models through the owning provider module."""
    if provider_name == "openai_codex":
        from nanobot.providers.openai_codex_provider import get_openai_codex_model_catalog

        return get_openai_codex_model_catalog(proxy)
    if provider_name == "xai_grok":
        from nanobot.providers.xai_grok_provider import get_xai_grok_model_catalog

        return get_xai_grok_model_catalog(proxy)
    if provider_name == "github_copilot":
        from nanobot.providers.github_copilot_provider import get_github_copilot_model_catalog

        return get_github_copilot_model_catalog(proxy)
    raise ValueError(f"OAuth model discovery is not available for {provider_name}")


def invalidate_oauth_model_catalog(provider_name: str) -> None:
    """Invalidate provider discovery after its OAuth identity changes."""
    if provider_name == "openai_codex":
        from nanobot.providers.openai_codex_provider import (
            invalidate_openai_codex_model_catalog,
        )

        invalidate_openai_codex_model_catalog()
    elif provider_name == "xai_grok":
        from nanobot.providers.xai_grok_provider import invalidate_xai_grok_model_catalog

        invalidate_xai_grok_model_catalog()
    elif provider_name == "github_copilot":
        from nanobot.providers.github_copilot_provider import (
            invalidate_github_copilot_model_catalog,
        )

        invalidate_github_copilot_model_catalog()
