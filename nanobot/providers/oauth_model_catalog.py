"""Online model discovery for OAuth providers with bounded local fallback."""

# oauth-cli-kit does not publish type stubs.
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import base64
import hashlib
import json
import os
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
DEFAULT_OPENAI_CODEX_MODELS_URL = "https://chatgpt.com/backend-api/codex/models"
OPENAI_CODEX_CATALOG_CLIENT_VERSION = "0.144.0"

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
        self._generation = 0

    def get(self, *, cache_key: str, proxy: str | None = None) -> OAuthModelCatalogSnapshot:
        """Return a fresh catalog, sharing concurrent work and failing to a usable list."""
        while True:
            with self._condition:
                cached = self._cached_result(cache_key)
                if cached is not None:
                    return cached
                while cache_key in self._inflight:
                    self._condition.wait()
                    cached = self._cached_result(cache_key)
                    if cached is not None:
                        return cached
                generation = self._generation
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
                with self._condition:
                    invalidated = generation != self._generation
                    result = self._failure_result(cache_key) if not invalidated else None
            else:
                now = self._monotonic()
                result = OAuthModelCatalogSnapshot(
                    models=models,
                    source="remote",
                    fetched_at=self._wall_clock(),
                )
                with self._condition:
                    invalidated = generation != self._generation
                    if not invalidated:
                        self._store(cache_key, _CacheEntry(snapshot=result, stored_at=now))
                        self._failures.pop(cache_key, None)
            finally:
                with self._condition:
                    self._inflight.discard(cache_key)
                    self._condition.notify_all()

            if invalidated:
                continue
            assert result is not None
            return result

    def invalidate(self) -> None:
        """Drop cached work and prevent an older account refresh from being stored."""
        with self._condition:
            self._generation += 1
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

_CURATED_OPENAI_CODEX_MODELS = (
    OAuthModelInfo(
        id="openai-codex/gpt-5.6-sol",
        label="GPT-5.6-Sol",
        description="Latest frontier agentic coding model.",
        owned_by="OpenAI Codex",
        context_window=272_000,
        reasoning_efforts=("low", "medium", "high", "xhigh", "max", "ultra"),
    ),
    OAuthModelInfo(
        id="openai-codex/gpt-5.6-terra",
        label="GPT-5.6-Terra",
        description="Balanced agentic coding model for everyday work.",
        owned_by="OpenAI Codex",
        context_window=272_000,
        reasoning_efforts=("low", "medium", "high", "xhigh", "max", "ultra"),
    ),
    OAuthModelInfo(
        id="openai-codex/gpt-5.6-luna",
        label="GPT-5.6-Luna",
        description="Fast and affordable agentic coding model.",
        owned_by="OpenAI Codex",
        context_window=272_000,
        reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
    ),
    OAuthModelInfo(
        id="openai-codex/gpt-5.5",
        label="GPT-5.5",
        description="Frontier model for complex coding, research, and real-world work.",
        owned_by="OpenAI Codex",
        context_window=272_000,
        reasoning_efforts=("low", "medium", "high", "xhigh"),
    ),
    OAuthModelInfo(
        id="openai-codex/gpt-5.4",
        label="GPT-5.4",
        description="Strong model for everyday coding.",
        owned_by="OpenAI Codex",
        context_window=272_000,
        reasoning_efforts=("low", "medium", "high", "xhigh"),
    ),
    OAuthModelInfo(
        id="openai-codex/gpt-5.4-mini",
        label="GPT-5.4-Mini",
        description="Small, fast, and cost-efficient model for simpler coding tasks.",
        owned_by="OpenAI Codex",
        context_window=272_000,
        reasoning_efforts=("low", "medium", "high", "xhigh"),
    ),
    OAuthModelInfo(
        id="openai-codex/gpt-5.3-codex-spark",
        label="GPT-5.3-Codex-Spark",
        description="Ultra-fast coding model.",
        owned_by="OpenAI Codex",
        context_window=128_000,
        reasoning_efforts=("low", "medium", "high", "xhigh"),
    ),
)

_CURATED_GITHUB_COPILOT_MODELS = (
    OAuthModelInfo(
        id="github-copilot/gpt-4.1",
        label="GPT-4.1",
        description="GitHub Copilot chat model.",
        owned_by="GitHub Copilot",
    ),
)


def curated_oauth_models(provider_name: str) -> tuple[OAuthModelInfo, ...]:
    """Return stable metadata used only to enrich or backstop online discovery."""
    if provider_name == "xai_grok":
        return _CURATED_XAI_GROK_MODELS
    if provider_name == "openai_codex":
        return _CURATED_OPENAI_CODEX_MODELS
    if provider_name == "github_copilot":
        return _CURATED_GITHUB_COPILOT_MODELS
    return ()


def get_oauth_model_catalog(
    provider_name: str,
    *,
    proxy: str | None = None,
) -> OAuthModelCatalogSnapshot:
    """Discover models for a supported OAuth provider."""
    if provider_name == "xai_grok":
        cache_key = f"{_xai_oauth_storage_path()}\0{_xai_account_key()}\0{proxy or ''}"
        return _XAI_GROK_CATALOG.get(cache_key=cache_key, proxy=proxy)
    if provider_name == "openai_codex":
        cache_key = (
            f"{_openai_codex_storage_path()}\0{_openai_codex_account_key()}\0{proxy or ''}"
        )
        return _OPENAI_CODEX_CATALOG.get(cache_key=cache_key, proxy=proxy)
    if provider_name == "github_copilot":
        cache_key = (
            f"{_github_copilot_storage_path()}\0{_github_copilot_account_key()}\0"
            f"{_github_copilot_models_url()}"
        )
        return _GITHUB_COPILOT_CATALOG.get(cache_key=cache_key, proxy=proxy)
    raise ValueError(f"OAuth model discovery is not available for {provider_name}")


def invalidate_oauth_model_catalog(provider_name: str) -> None:
    """Invalidate provider discovery after OAuth identity changes."""
    catalog = _OAUTH_CATALOGS.get(provider_name)
    if catalog is not None:
        catalog.invalidate()


def _fetch_openai_codex_models(proxy: str | None) -> tuple[OAuthModelInfo, ...]:
    from oauth_cli_kit import get_token as get_codex_token

    token = get_codex_token(proxy=proxy)
    account_id = getattr(token, "account_id", None)
    if not isinstance(account_id, str) or not account_id:
        raise RuntimeError("OpenAI Codex OAuth token has no account ID")
    client_kwargs: dict[str, Any] = {"timeout": 10.0, "follow_redirects": False}
    if proxy:
        client_kwargs.update(proxy=proxy, trust_env=False)
    with httpx.Client(**client_kwargs) as client:
        response = client.get(
            DEFAULT_OPENAI_CODEX_MODELS_URL,
            params={"client_version": OPENAI_CODEX_CATALOG_CLIENT_VERSION},
            headers={
                "Authorization": f"Bearer {token.access}",
                "chatgpt-account-id": account_id,
                "originator": "nanobot",
                "User-Agent": f"nanobot/{__version__} (python)",
                "accept": "application/json",
            },
        )
    response.raise_for_status()
    return _parse_openai_codex_models(response.json())


def _parse_openai_codex_models(payload: Any) -> tuple[OAuthModelInfo, ...]:
    rows = cast(dict[str, Any], payload).get("models") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return ()

    curated = {model.wire_id: model for model in _CURATED_OPENAI_CODEX_MODELS}
    parsed: list[tuple[int, OAuthModelInfo]] = []
    seen: set[str] = set()
    for value in cast(list[object], rows):
        if not isinstance(value, dict):
            continue
        row = cast(dict[str, Any], value)
        wire_id = _first_text(row, "slug", "id")
        if not wire_id or wire_id in seen or row.get("visibility") in {"hide", "none"}:
            continue
        seen.add(wire_id)
        fallback = curated.get(wire_id)
        label = _first_text(row, "display_name", "name")
        description = _first_text(row, "description")
        priority = row.get("priority")
        parsed.append(
            (
                priority if isinstance(priority, int) and not isinstance(priority, bool) else 2**31,
                OAuthModelInfo(
                    id=f"openai-codex/{wire_id}",
                    label=label or (fallback.label if fallback is not None else wire_id),
                    description=(
                        description
                        or (fallback.description if fallback is not None else "")
                    ),
                    owned_by="OpenAI Codex",
                    context_window=(
                        _positive_int(row, "context_window")
                        or (fallback.context_window if fallback is not None else None)
                    ),
                    reasoning_efforts=(
                        _reasoning_efforts(row.get("supported_reasoning_levels"))
                        or (fallback.reasoning_efforts if fallback is not None else ())
                    ),
                ),
            )
        )
    parsed.sort(key=lambda item: item[0])
    return tuple(model for _, model in parsed)


def _fetch_github_copilot_models(proxy: str | None) -> tuple[OAuthModelInfo, ...]:
    from nanobot.providers.github_copilot_provider import (
        DEFAULT_COPILOT_TOKEN_URL,
        EDITOR_PLUGIN_VERSION,
        EDITOR_VERSION,
        USER_AGENT,
        get_storage,
    )

    github_token = get_storage().load()
    if not github_token or not github_token.access:
        raise RuntimeError("GitHub Copilot is not logged in")

    common_headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "Editor-Version": EDITOR_VERSION,
        "Editor-Plugin-Version": EDITOR_PLUGIN_VERSION,
    }
    client_kwargs: dict[str, Any] = {"timeout": 20.0, "follow_redirects": True}
    if proxy:
        client_kwargs.update(proxy=proxy, trust_env=False)
    with httpx.Client(**client_kwargs) as client:
        exchange = client.get(
            os.environ.get("NANOBOT_COPILOT_TOKEN_URL", "").strip()
            or DEFAULT_COPILOT_TOKEN_URL,
            headers={**common_headers, "Authorization": f"token {github_token.access}"},
        )
        exchange.raise_for_status()
        exchange_payload = exchange.json()
        exchange_mapping = _mapping(exchange_payload)
        copilot_token = (
            exchange_mapping.get("token") if exchange_mapping else None
        )
        if not isinstance(copilot_token, str) or not copilot_token:
            raise RuntimeError("GitHub Copilot token exchange returned no token")
        endpoint_base = _first_text(_mapping(exchange_mapping.get("endpoints")), "api")
        if endpoint_base:
            models_url = (
                endpoint_base
                if endpoint_base.rstrip("/").endswith("/models")
                else f"{endpoint_base.rstrip('/')}/models"
            )
        else:
            models_url = _github_copilot_models_url()
        response = client.get(
            models_url,
            headers={**common_headers, "Authorization": f"Bearer {copilot_token}"},
        )
    response.raise_for_status()
    return _parse_github_copilot_models(response.json())


def _parse_github_copilot_models(payload: Any) -> tuple[OAuthModelInfo, ...]:
    rows = cast(dict[str, Any], payload).get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return ()

    curated = {model.wire_id: model for model in _CURATED_GITHUB_COPILOT_MODELS}
    models: list[OAuthModelInfo] = []
    seen: set[str] = set()
    for value in cast(list[object], rows):
        if not isinstance(value, dict):
            continue
        row = cast(dict[str, Any], value)
        wire_id = _first_text(row, "id")
        policy = _mapping(row.get("policy"))
        endpoints = row.get("supported_endpoints")
        if (
            not wire_id
            or wire_id in seen
            or row.get("model_picker_enabled") is not True
            or policy.get("state") == "disabled"
            or (
                isinstance(endpoints, list)
                and "/chat/completions" not in cast(list[object], endpoints)
            )
        ):
            continue
        seen.add(wire_id)
        capabilities = _mapping(row.get("capabilities"))
        supports = _mapping(capabilities.get("supports"))
        limits = _mapping(capabilities.get("limits"))
        fallback = curated.get(wire_id)
        models.append(
            OAuthModelInfo(
                id=f"github-copilot/{wire_id}",
                label=(
                    _first_text(row, "name")
                    or (fallback.label if fallback is not None else wire_id)
                ),
                description=(fallback.description if fallback is not None else ""),
                owned_by="GitHub Copilot",
                context_window=(
                    _positive_int(limits, "max_context_window_tokens")
                    or (fallback.context_window if fallback is not None else None)
                ),
                reasoning_efforts=_reasoning_efforts(supports.get("reasoning_effort")),
            )
        )
    return tuple(models)


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


def _mapping(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


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
            effort = _first_text(cast(dict[str, Any], item), "effort", "value", "id")
        else:
            effort = ""
        if effort and effort not in efforts:
            efforts.append(effort)
    return tuple(efforts)


def _xai_oauth_storage_path() -> Path:
    from nanobot.providers.xai_oauth import get_xai_oauth_storage_path

    return get_xai_oauth_storage_path()


def _account_key(account_id: object) -> str:
    value = account_id if isinstance(account_id, str) else ""
    return hashlib.sha256(value.encode()).hexdigest()[:16] if value else "anonymous"


def _xai_account_key() -> str:
    from nanobot.providers.xai_oauth import get_xai_oauth_login_status

    token = get_xai_oauth_login_status()
    return _account_key(getattr(token, "account_id", None))


def _openai_codex_storage_path() -> Path:
    from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
    from oauth_cli_kit.storage import FileTokenStorage

    return FileTokenStorage(token_filename=OPENAI_CODEX_PROVIDER.token_filename).get_token_path()


def _openai_codex_account_key() -> str:
    from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
    from oauth_cli_kit.storage import FileTokenStorage

    token = FileTokenStorage(token_filename=OPENAI_CODEX_PROVIDER.token_filename).load()
    return _account_key(getattr(token, "account_id", None))


def _github_copilot_storage_path() -> Path:
    from nanobot.providers.github_copilot_provider import get_storage

    return get_storage().get_token_path()


def _github_copilot_account_key() -> str:
    from nanobot.providers.github_copilot_provider import get_storage

    token = get_storage().load()
    return _account_key(getattr(token, "account_id", None))


def _github_copilot_models_url() -> str:
    from nanobot.providers.github_copilot_provider import DEFAULT_COPILOT_BASE_URL

    base_url = (
        os.environ.get("NANOBOT_COPILOT_BASE_URL", "").strip()
        or DEFAULT_COPILOT_BASE_URL
    )
    return f"{base_url.rstrip('/')}/models"


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
_OPENAI_CODEX_CATALOG = OAuthModelCatalog(
    fallback_models=_CURATED_OPENAI_CODEX_MODELS,
    fetch=_fetch_openai_codex_models,
)
_GITHUB_COPILOT_CATALOG = OAuthModelCatalog(
    fallback_models=_CURATED_GITHUB_COPILOT_MODELS,
    fetch=_fetch_github_copilot_models,
)
_OAUTH_CATALOGS = {
    "xai_grok": _XAI_GROK_CATALOG,
    "openai_codex": _OPENAI_CODEX_CATALOG,
    "github_copilot": _GITHUB_COPILOT_CATALOG,
}
