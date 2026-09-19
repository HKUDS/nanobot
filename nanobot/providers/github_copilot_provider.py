"""GitHub Copilot OAuth-backed provider."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import asyncio
import hashlib
import os
import time
import webbrowser
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any, cast

import httpx
from oauth_cli_kit.models import OAuthToken
from oauth_cli_kit.storage import FileTokenStorage

from nanobot.providers.base import LLMResponse, ProviderCallContext
from nanobot.providers.oauth_model_catalog import (
    OAuthModelCatalog,
    OAuthModelCatalogSnapshot,
)
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import ProviderModelSpec, find_by_name

DEFAULT_GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
DEFAULT_GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
DEFAULT_GITHUB_USER_URL = "https://api.github.com/user"
DEFAULT_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
DEFAULT_COPILOT_BASE_URL = "https://api.githubcopilot.com"
GITHUB_COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"
GITHUB_COPILOT_SCOPE = "read:user"
TOKEN_FILENAME = "github-copilot.json"
TOKEN_APP_NAME = "nanobot"
USER_AGENT = "nanobot/0.1"
EDITOR_VERSION = "vscode/1.99.0"
EDITOR_PLUGIN_VERSION = "copilot-chat/0.26.0"
_EXPIRY_SKEW_SECONDS = 60
_LONG_LIVED_TOKEN_SECONDS = 315360000


def _resolve(env_var: str, default: str) -> str:
    """Allow GitHub Enterprise / Copilot for Business deployments to override defaults via env."""
    value = os.environ.get(env_var)
    return value.strip() if value and value.strip() else default


def get_storage() -> FileTokenStorage:
    return FileTokenStorage(
        token_filename=TOKEN_FILENAME,
        app_name=TOKEN_APP_NAME,
        import_codex_cli=False,
    )


def _copilot_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "Editor-Version": EDITOR_VERSION,
        "Editor-Plugin-Version": EDITOR_PLUGIN_VERSION,
    }


def _load_github_token() -> OAuthToken | None:
    token = get_storage().load()
    if not token or not token.access:
        return None
    return token


def get_github_copilot_login_status() -> OAuthToken | None:
    """Return the persisted GitHub OAuth token if available."""
    return _load_github_token()


def login_github_copilot(
    print_fn: Callable[[str], None] | None = None,
    prompt_fn: Callable[[str], str] | None = None,
) -> OAuthToken:
    """Run GitHub device flow and persist the GitHub OAuth token used for Copilot."""
    del prompt_fn
    printer = print_fn or print
    timeout = httpx.Timeout(20.0, connect=20.0)

    client_id = _resolve("NANOBOT_GITHUB_COPILOT_CLIENT_ID", GITHUB_COPILOT_CLIENT_ID)
    device_code_url = _resolve("NANOBOT_GITHUB_DEVICE_CODE_URL", DEFAULT_GITHUB_DEVICE_CODE_URL)
    access_token_url = _resolve("NANOBOT_GITHUB_ACCESS_TOKEN_URL", DEFAULT_GITHUB_ACCESS_TOKEN_URL)
    user_url = _resolve("NANOBOT_GITHUB_USER_URL", DEFAULT_GITHUB_USER_URL)

    with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=True) as client:
        response = client.post(
            device_code_url,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            data={"client_id": client_id, "scope": GITHUB_COPILOT_SCOPE},
        )
        response.raise_for_status()
        payload = response.json()

        device_code = str(payload["device_code"])
        user_code = str(payload["user_code"])
        verify_url = str(
            payload.get("verification_uri") or payload.get("verification_uri_complete") or ""
        )
        verify_complete = str(payload.get("verification_uri_complete") or verify_url)
        interval = max(1, int(payload.get("interval") or 5))
        expires_in = int(payload.get("expires_in") or 900)

        printer(f"Open: {verify_url}")
        printer(f"Code: {user_code}")
        if verify_complete:
            with suppress(Exception):
                webbrowser.open(verify_complete)

        deadline = time.time() + expires_in
        current_interval = interval
        access_token = None
        token_expires_in = _LONG_LIVED_TOKEN_SECONDS
        while time.time() < deadline:
            poll = client.post(
                access_token_url,
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                data={
                    "client_id": client_id,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
            poll.raise_for_status()
            poll_payload = poll.json()

            access_token = poll_payload.get("access_token")
            if access_token:
                token_expires_in = int(poll_payload.get("expires_in") or _LONG_LIVED_TOKEN_SECONDS)
                break

            error = poll_payload.get("error")
            if error == "authorization_pending":
                time.sleep(current_interval)
                continue
            if error == "slow_down":
                current_interval += 5
                time.sleep(current_interval)
                continue
            if error == "expired_token":
                raise RuntimeError("GitHub device code expired. Please run login again.")
            if error == "access_denied":
                raise RuntimeError("GitHub device flow was denied.")
            if error:
                desc = poll_payload.get("error_description") or error
                raise RuntimeError(str(desc))
            time.sleep(current_interval)
        else:
            raise RuntimeError("GitHub device flow timed out.")

        user = client.get(
            user_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT,
            },
        )
        user.raise_for_status()
        user_payload = user.json()
        account_id = user_payload.get("login") or str(user_payload.get("id") or "") or None

    expires_ms = int((time.time() + token_expires_in) * 1000)
    token = OAuthToken(
        access=str(access_token),
        refresh="",
        expires=expires_ms,
        account_id=str(account_id) if account_id else None,
    )
    get_storage().save(token)
    return token


class GitHubCopilotProvider(OpenAICompatProvider):
    """Provider that exchanges a stored GitHub OAuth token for Copilot access tokens."""

    def __init__(
        self,
        default_model: str = "github-copilot/gpt-4.1",
        *,
        provider_name: str = "github_copilot",
    ):
        self._copilot_access_token: str | None = None
        self._copilot_expires_at: float = 0.0
        self._copilot_token_lock: asyncio.Lock = asyncio.Lock()
        super().__init__(
            api_key="no-key",
            api_base=_resolve("NANOBOT_COPILOT_BASE_URL", DEFAULT_COPILOT_BASE_URL),
            default_model=default_model,
            extra_headers={
                "Editor-Version": EDITOR_VERSION,
                "Editor-Plugin-Version": EDITOR_PLUGIN_VERSION,
                "User-Agent": USER_AGENT,
            },
            spec=find_by_name("github_copilot"),
            provider_name=provider_name,
        )

    async def _get_copilot_access_token(self) -> str:
        now = time.time()
        if self._copilot_access_token and now < self._copilot_expires_at - _EXPIRY_SKEW_SECONDS:
            return self._copilot_access_token

        async with self._copilot_token_lock:
            # Re-check after acquiring the lock: another task may have refreshed
            # the token while we were waiting.
            now = time.time()
            if self._copilot_access_token and now < self._copilot_expires_at - _EXPIRY_SKEW_SECONDS:
                return self._copilot_access_token

            github_token = _load_github_token()
            if not github_token or not github_token.access:
                raise RuntimeError(
                    "GitHub Copilot is not logged in. Run: nanobot provider login github-copilot"
                )

            timeout = httpx.Timeout(20.0, connect=20.0)
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=True, trust_env=True
            ) as client:
                response = await client.get(
                    _resolve("NANOBOT_COPILOT_TOKEN_URL", DEFAULT_COPILOT_TOKEN_URL),
                    headers=_copilot_headers(github_token.access),
                )
                response.raise_for_status()
                payload = response.json()

            token = payload.get("token")
            if not token:
                raise RuntimeError("GitHub Copilot token exchange returned no token.")

            expires_at = payload.get("expires_at")
            if isinstance(expires_at, (int, float)):
                self._copilot_expires_at = float(expires_at)
            else:
                refresh_in = payload.get("refresh_in") or 1500
                self._copilot_expires_at = time.time() + int(refresh_in)
            self._copilot_access_token = str(token)
            return self._copilot_access_token

    async def _refresh_client_api_key(self) -> str:
        token = await self._get_copilot_access_token()
        client = await self._ensure_client()
        self.api_key = token
        cast(Any, client).api_key = token
        return token

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        provider_context: ProviderCallContext | None = None,
    ) -> LLMResponse:
        await self._refresh_client_api_key()
        return await super().chat(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            provider_context=provider_context,
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        provider_context: ProviderCallContext | None = None,
    ) -> LLMResponse:
        await self._refresh_client_api_key()
        return await super().chat_stream(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            on_content_delta=on_content_delta,
            on_thinking_delta=on_thinking_delta,
            on_tool_call_delta=on_tool_call_delta,
            provider_context=provider_context,
        )


def get_github_copilot_model_catalog(
    proxy: str | None = None,
) -> OAuthModelCatalogSnapshot:
    storage = get_storage()
    token = storage.load()
    account_key = _catalog_account_key(getattr(token, "account_id", None))
    cache_key = (
        f"{storage.get_token_path()}\0{account_key}\0"
        f"{_resolve('NANOBOT_COPILOT_BASE_URL', DEFAULT_COPILOT_BASE_URL)}\0{proxy or ''}"
    )
    return _GITHUB_COPILOT_MODEL_CATALOG.get(cache_key=cache_key, proxy=proxy)


def invalidate_github_copilot_model_catalog() -> None:
    _GITHUB_COPILOT_MODEL_CATALOG.invalidate()


def _fetch_github_copilot_models(proxy: str | None) -> tuple[ProviderModelSpec, ...]:
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
            _resolve("NANOBOT_COPILOT_TOKEN_URL", DEFAULT_COPILOT_TOKEN_URL),
            headers={**common_headers, "Authorization": f"token {github_token.access}"},
        )
        exchange.raise_for_status()
        exchange_mapping = _catalog_mapping(exchange.json())
        copilot_token = exchange_mapping.get("token")
        if not isinstance(copilot_token, str) or not copilot_token:
            raise RuntimeError("GitHub Copilot token exchange returned no token")
        endpoint_base = _catalog_first_text(
            _catalog_mapping(exchange_mapping.get("endpoints")),
            "api",
        )
        base_url = endpoint_base or _resolve(
            "NANOBOT_COPILOT_BASE_URL",
            DEFAULT_COPILOT_BASE_URL,
        )
        models_url = (
            base_url
            if base_url.rstrip("/").endswith("/models")
            else f"{base_url.rstrip('/')}/models"
        )
        response = client.get(
            models_url,
            headers={**common_headers, "Authorization": f"Bearer {copilot_token}"},
        )
    response.raise_for_status()
    return _parse_github_copilot_models(response.json())


def _parse_github_copilot_models(payload: Any) -> tuple[ProviderModelSpec, ...]:
    rows = cast(dict[str, Any], payload).get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return ()

    fallback_models = _oauth_fallback_models("github_copilot")
    fallback_by_id = {model.id.split("/", 1)[-1]: model for model in fallback_models}
    models: list[ProviderModelSpec] = []
    seen: set[str] = set()
    for value in cast(list[object], rows):
        if not isinstance(value, dict):
            continue
        row = cast(dict[str, Any], value)
        wire_id = _catalog_first_text(row, "id")
        policy = _catalog_mapping(row.get("policy"))
        endpoints = row.get("supported_endpoints")
        if (
            not wire_id
            or wire_id in seen
            or row.get("model_picker_enabled") is not True
            or policy.get("state") == "disabled"
            or not _copilot_transport_supported(wire_id, endpoints)
        ):
            continue
        seen.add(wire_id)
        capabilities = _catalog_mapping(row.get("capabilities"))
        supports = _catalog_mapping(capabilities.get("supports"))
        limits = _catalog_mapping(capabilities.get("limits"))
        fallback = fallback_by_id.get(wire_id)
        models.append(
            ProviderModelSpec(
                id=f"github-copilot/{wire_id}",
                label=(
                    _catalog_first_text(row, "name")
                    or (fallback.label if fallback is not None else wire_id)
                ),
                description=(fallback.description if fallback is not None else ""),
                owned_by="GitHub Copilot",
                context_window=(
                    _catalog_positive_int(limits, "max_context_window_tokens")
                    or (fallback.context_window if fallback is not None else None)
                ),
                reasoning_efforts=_catalog_reasoning_efforts(supports.get("reasoning_effort")),
            )
        )
    return tuple(models)


def _copilot_transport_supported(wire_id: str, endpoints: object) -> bool:
    if not isinstance(endpoints, list):
        return True
    supported = cast(list[object], endpoints)
    if "/chat/completions" in supported:
        return True
    model = wire_id.lower()
    return "/responses" in supported and any(
        token in model for token in ("gpt-5", "o1", "o3", "o4")
    )


def _oauth_fallback_models(provider_name: str) -> tuple[ProviderModelSpec, ...]:
    spec = find_by_name(provider_name)
    assert spec is not None
    return spec.builtin_models


def _catalog_account_key(account_id: object) -> str:
    value = account_id if isinstance(account_id, str) else ""
    return hashlib.sha256(value.encode()).hexdigest()[:16] if value else "anonymous"


def _catalog_mapping(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _catalog_first_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _catalog_positive_int(row: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return int(value)
    return None


def _catalog_reasoning_efforts(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        dict.fromkeys(
            item.strip()
            for item in cast(list[object], value)
            if isinstance(item, str) and item.strip()
        )
    )


_GITHUB_COPILOT_MODEL_CATALOG = OAuthModelCatalog(
    fallback_models=_oauth_fallback_models("github_copilot"),
    fetch=_fetch_github_copilot_models,
)
