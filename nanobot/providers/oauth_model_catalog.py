"""Online model discovery for OAuth providers with bounded local fallback."""

from __future__ import annotations

import base64
import json
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import httpx
from loguru import logger

from nanobot import __version__

DEFAULT_XAI_GROK_MODEL = "xai-grok/grok-4.6"
DEFAULT_XAI_GROK_MODELS_URL = "https://cli-chat-proxy.grok.com/v1/models"

CatalogSource = Literal["remote", "cache", "stale", "fallback"]


class _XAIToken(Protocol):
    @property
    def access(self) -> str: ...

    @property
    def account_id(self) -> str | None: ...


@dataclass(frozen=True)
class OAuthModelInfo:
    """Normalized provider model metadata used by settings and runtimes."""

    id: str
    label: str
    description: str = ""
    owned_by: str = ""
    context_window: int | None = None
    reasoning_efforts: tuple[str, ...] = ()
    supports_backend_search: bool = False

    @property
    def wire_id(self) -> str:
        return self.id.split("/", 1)[-1]


@dataclass(frozen=True)
class OAuthModelCatalogSnapshot:
    """One usable catalog view, including where it came from."""

    models: tuple[OAuthModelInfo, ...]
    source: CatalogSource
    fetched_at: float
    message: str | None = None

    def find(self, model: str) -> OAuthModelInfo | None:
        wire_id = model.split("/", 1)[-1]
        return next((item for item in self.models if item.wire_id == wire_id), None)


@dataclass(frozen=True)
class _CacheEntry:
    snapshot: OAuthModelCatalogSnapshot
    stored_at: float


class OAuthModelCatalog:
    """Cache remote discovery behind one thread-safe, failure-tolerant interface."""

    def __init__(
        self,
        *,
        fallback_models: Sequence[OAuthModelInfo],
        fetch: Callable[[str | None], Sequence[OAuthModelInfo]],
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

    def get(self, *, cache_key: str, proxy: str | None = None) -> OAuthModelCatalogSnapshot:
        """Return a fresh catalog, sharing concurrent work and failing to a usable list."""
        with self._condition:
            cached = self._cached_result(cache_key)
            if cached is not None:
                return cached
            while cache_key in self._inflight:
                self._condition.wait()
                cached = self._cached_result(cache_key)
                if cached is not None:
                    return cached
            self._inflight.add(cache_key)

        try:
            models = tuple(self._fetch(proxy))
            if not models:
                raise ValueError("provider returned an empty model catalog")
        except Exception as exc:
            logger.warning(
                "OAuth model catalog refresh failed: type={}",
                type(exc).__name__,
            )
            result = self._failure_result(cache_key)
        else:
            now = self._monotonic()
            result = OAuthModelCatalogSnapshot(
                models=models,
                source="remote",
                fetched_at=self._wall_clock(),
            )
            with self._condition:
                self._store(cache_key, _CacheEntry(snapshot=result, stored_at=now))
                self._failures.pop(cache_key, None)
        finally:
            with self._condition:
                self._inflight.discard(cache_key)
                self._condition.notify_all()
        return result

    def invalidate(self) -> None:
        """Drop cached and negative results, for example after account changes."""
        with self._condition:
            self._entries.clear()
            self._failures.clear()

    def _cached_result(self, cache_key: str) -> OAuthModelCatalogSnapshot | None:
        now = self._monotonic()
        entry = self._entries.get(cache_key)
        if entry is not None and now - entry.stored_at < self._fresh_ttl_s:
            return replace(entry.snapshot, source="cache")
        failure_until = self._failures.get(cache_key, 0)
        if failure_until > now:
            return self._stale_or_fallback(entry, now)
        return None

    def _failure_result(self, cache_key: str) -> OAuthModelCatalogSnapshot:
        with self._condition:
            now = self._monotonic()
            self._failures[cache_key] = now + self._failure_ttl_s
            return self._stale_or_fallback(self._entries.get(cache_key), now)

    def _stale_or_fallback(
        self,
        entry: _CacheEntry | None,
        now: float,
    ) -> OAuthModelCatalogSnapshot:
        message = "Could not refresh the online model list; showing cached models."
        if entry is not None and now - entry.stored_at < self._stale_ttl_s:
            return replace(entry.snapshot, source="stale", message=message)
        return OAuthModelCatalogSnapshot(
            models=self._fallback_models,
            source="fallback",
            fetched_at=self._wall_clock(),
            message="Could not load the online model list; showing built-in fallback models.",
        )

    def _store(self, cache_key: str, entry: _CacheEntry) -> None:
        if cache_key not in self._entries and len(self._entries) >= self._max_entries:
            oldest = min(self._entries, key=lambda key: self._entries[key].stored_at)
            self._entries.pop(oldest, None)
            self._failures.pop(oldest, None)
        self._entries[cache_key] = entry


_CURATED_XAI_GROK_MODELS = (
    OAuthModelInfo(
        id="xai-grok/grok-4.6",
        label="Grok 4.6",
        description="Grok via xAI subscription; X Search is enabled when supported.",
        owned_by="xAI Grok",
        context_window=500_000,
    ),
    OAuthModelInfo(
        id="xai-grok/grok-4.5",
        label="Grok 4.5",
        description="Grok via xAI subscription; X Search is enabled when supported.",
        owned_by="xAI Grok",
        context_window=500_000,
    ),
)


def curated_oauth_models(provider_name: str) -> tuple[OAuthModelInfo, ...]:
    """Return stable metadata used only to enrich or backstop online discovery."""
    if provider_name == "xai_grok":
        return _CURATED_XAI_GROK_MODELS
    return ()


def get_oauth_model_catalog(
    provider_name: str,
    *,
    proxy: str | None = None,
) -> OAuthModelCatalogSnapshot:
    """Discover models for a supported OAuth provider."""
    if provider_name != "xai_grok":
        raise ValueError(f"OAuth model discovery is not available for {provider_name}")
    cache_key = f"{_xai_oauth_storage_path()}\0{proxy or ''}"
    return _XAI_GROK_CATALOG.get(cache_key=cache_key, proxy=proxy)


def invalidate_oauth_model_catalog(provider_name: str) -> None:
    """Invalidate provider discovery after OAuth identity changes."""
    if provider_name == "xai_grok":
        _XAI_GROK_CATALOG.invalidate()


def _fetch_xai_grok_models(proxy: str | None) -> tuple[OAuthModelInfo, ...]:
    token = _xai_oauth_token(proxy)
    client_kwargs: dict[str, Any] = {"timeout": 10.0, "follow_redirects": False}
    if proxy:
        client_kwargs.update(proxy=proxy, trust_env=False)
    with httpx.Client(**client_kwargs) as client:
        response = client.get(
            DEFAULT_XAI_GROK_MODELS_URL,
            headers=_build_xai_model_headers(token),
        )
    response.raise_for_status()
    return _parse_xai_grok_models(response.json())


def _parse_xai_grok_models(payload: Any) -> tuple[OAuthModelInfo, ...]:
    if isinstance(payload, dict):
        payload_mapping = cast(dict[str, Any], payload)
        rows: object = payload_mapping.get("data")
        if not isinstance(rows, list):
            rows = payload_mapping.get("models")
    else:
        rows = payload
    if not isinstance(rows, list):
        return ()

    curated = {model.wire_id: model for model in _CURATED_XAI_GROK_MODELS}
    models: list[OAuthModelInfo] = []
    seen: set[str] = set()
    for value in cast(list[object], rows):
        if not isinstance(value, dict):
            continue
        row = cast(dict[str, Any], value)
        meta_value = row.get("_meta")
        meta = cast(dict[str, Any], meta_value) if isinstance(meta_value, dict) else {}
        raw_id = next(
            (
                candidate.strip()
                for candidate in (
                    row.get("id"),
                    row.get("model"),
                    row.get("modelId"),
                    row.get("name"),
                    meta.get("id"),
                    meta.get("model"),
                    meta.get("modelId"),
                )
                if isinstance(candidate, str) and candidate.strip()
            ),
            None,
        )
        if raw_id is None:
            continue
        wire_id = raw_id.split("/", 1)[-1]
        if wire_id in seen:
            continue
        seen.add(wire_id)
        fallback = curated.get(wire_id)
        model_id = f"xai-grok/{wire_id}"
        label = _first_text(row, "display_name", "label", "name") or _first_text(
            meta,
            "display_name",
            "label",
            "name",
        )
        if not label or label == raw_id:
            label = fallback.label if fallback is not None else wire_id
        description = _first_text(row, "description") or _first_text(meta, "description")
        owner = _first_text(row, "owned_by", "owner", "organization") or _first_text(
            meta,
            "owned_by",
            "owner",
            "organization",
        )
        models.append(
            OAuthModelInfo(
                id=model_id,
                label=label,
                description=(
                    description
                    or (fallback.description if fallback is not None else "")
                ),
                owned_by=owner or (fallback.owned_by if fallback is not None else "xAI"),
                context_window=(
                    _positive_int(row, "context_window", "context_length")
                    or _positive_int(meta, "context_window", "context_length")
                    or (fallback.context_window if fallback is not None else None)
                ),
                reasoning_efforts=_reasoning_efforts(
                    row.get("reasoning_efforts", meta.get("reasoning_efforts"))
                ),
                supports_backend_search=_bool_field(
                    row,
                    "supports_backend_search",
                    "supportsBackendSearch",
                ),
            )
        )
    return tuple(models)


def _first_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _positive_int(row: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return int(value)
    return None


def _bool_field(row: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool):
            return value
    meta = row.get("_meta")
    if isinstance(meta, dict):
        return _bool_field(cast(dict[str, Any], meta), *keys)
    return False


def _reasoning_efforts(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    efforts: list[str] = []
    for item in cast(list[object], value):
        if isinstance(item, str):
            effort = item.strip()
        elif isinstance(item, dict):
            effort = _first_text(cast(dict[str, Any], item), "value", "id")
        else:
            effort = ""
        if effort and effort not in efforts:
            efforts.append(effort)
    return tuple(efforts)


def _xai_oauth_storage_path() -> Path:
    from nanobot.providers.xai_oauth import get_xai_oauth_storage_path

    return get_xai_oauth_storage_path()


def _xai_oauth_token(proxy: str | None) -> _XAIToken:
    from nanobot.providers.xai_oauth import get_xai_oauth_token

    return get_xai_oauth_token(proxy=proxy)


def _build_xai_model_headers(token: _XAIToken) -> dict[str, str]:
    from nanobot.providers.xai_oauth import XAI_CLIENT_VERSION

    headers = {
        "Authorization": f"Bearer {token.access}",
        "X-XAI-Token-Auth": "xai-grok-cli",
        "x-grok-client-version": XAI_CLIENT_VERSION,
        "x-grok-client-identifier": "nanobot",
        "x-grok-client-mode": "headless",
        "User-Agent": f"nanobot/{__version__} (python)",
        "accept": "application/json",
    }
    claims = _decode_access_token_claims(token.access)
    user_id = claims.get("sub")
    if claims.get("principal_type") == "Team":
        user_id = claims.get("principal_id") or user_id
    if isinstance(user_id, str) and user_id:
        headers["x-userid"] = user_id
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email:
        email = token.account_id if token.account_id and "@" in token.account_id else None
    if email:
        headers["x-email"] = email
    return headers


def _decode_access_token_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2 or not parts[1]:
        return {}
    try:
        decoded = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        claims = json.loads(decoded)
    except (ValueError, TypeError):
        return {}
    return cast(dict[str, Any], claims) if isinstance(claims, dict) else {}


_XAI_GROK_CATALOG = OAuthModelCatalog(
    fallback_models=_CURATED_XAI_GROK_MODELS,
    fetch=_fetch_xai_grok_models,
)
