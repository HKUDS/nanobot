"""WebUI OAuth provider adapters; the service registry still owns live flows."""

# oauth-cli-kit does not publish type stubs.
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import secrets
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Generator, Literal, Protocol

from loguru import logger

from nanobot.config.loader import resolve_config_env_vars
from nanobot.providers.oauth_guidance import OAUTH_CLI_KIT_MISSING_MESSAGE
from nanobot.webui.settings_contracts import WebUISettingsError

if TYPE_CHECKING:
    from nanobot.config.schema import Config
    from nanobot.providers.registry import ProviderSpec
    from nanobot.webui.settings_services import (
        WebUIOAuthFlow,
        WebUIOAuthFlowRegistry,
        WebUIOAuthToken,
    )

_WEBUI_OAUTH_TIMEOUT_S = 600


if TYPE_CHECKING:
    class _StartableOAuthFlow(WebUIOAuthFlow, Protocol):
        @property
        def authorization_url(self) -> str: ...

        @property
        def remaining_seconds(self) -> int: ...

        def start(self) -> object: ...


@dataclass(frozen=True)
class _PendingLogin:
    flow: _StartableOAuthFlow
    user_code: Callable[[], str] | None = None


@dataclass(frozen=True)
class _LoginContext:
    config: Config
    config_path: Path | None
    remote_browser: Callable[[], bool]
    oauth_flows: WebUIOAuthFlowRegistry

    def proxy(self, provider: Literal["openai_codex", "xai_grok"]) -> str | None:
        try:
            resolved = resolve_config_env_vars(self.config, config_path=self.config_path)
            return resolved.network.resolve_proxy(getattr(resolved.providers, provider).use_proxy)
        except ValueError as exc:
            raise WebUISettingsError(str(exc), status=400) from exc


def _complete(flow: WebUIOAuthFlow, response: str | None) -> WebUIOAuthToken | None:
    return flow.complete(response)


@dataclass(frozen=True)
class OAuthProviderAdapter:
    completion_input: Literal["callback_url", "device_code", "authorization_code"]
    load_status: Callable[[], Callable[[], WebUIOAuthToken | None]]
    create_login: Callable[[_LoginContext], _PendingLogin]
    prepare_logout: Callable[[], Callable[[], object]]
    login_failure: Callable[[Exception], str]
    complete: Callable[[WebUIOAuthFlow, str | None], WebUIOAuthToken | None] = _complete
    supports_proxy: bool = False
    allow_refresh_token: bool = False
    disclose_login_error: bool = True

    def start_login(
        self, provider: str, config: Config, config_path: Path | None,
        remote_browser: Callable[[], bool], oauth_flows: WebUIOAuthFlowRegistry,
    ) -> dict[str, Any]:
        login = self.create_login(_LoginContext(config, config_path, remote_browser, oauth_flows))
        flow = login.flow
        flow_id = secrets.token_urlsafe(24)
        # Register before network I/O so cancellation also owns in-flight starts.
        try:
            oauth_flows.register(provider, flow_id, flow)
            flow.start()
        except Exception as exc:
            oauth_flows.remove(provider, flow_id, flow)
            raise WebUISettingsError(self.login_failure(exc), status=502) from (
                exc if self.disclose_login_error else None
            )
        result = {
            "status": "authorization_required",
            "provider": provider,
            "flow_id": flow_id,
            "authorization_url": flow.authorization_url,
            "expires_in": flow.remaining_seconds,
            "completion_input": self.completion_input,
        }
        if login.user_code is not None:
            result["user_code"] = login.user_code()
        return result

    def logout(self, provider: str, oauth_flows: WebUIOAuthFlowRegistry) -> None:
        revoke = self.prepare_logout()
        oauth_flows.clear(provider)
        revoke()


@contextmanager
def _oauth_cli_kit_import() -> Generator[None]:
    try:
        yield
    except ImportError:
        raise WebUISettingsError(OAUTH_CLI_KIT_MISSING_MESSAGE, status=500) from None


def _codex_status_loader() -> Callable[[], WebUIOAuthToken | None]:
    from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
    from oauth_cli_kit.storage import FileTokenStorage

    return lambda: FileTokenStorage(token_filename=OPENAI_CODEX_PROVIDER.token_filename).load()


def _copilot_status_loader() -> Callable[[], WebUIOAuthToken | None]:
    from nanobot.providers.github_copilot_provider import get_github_copilot_login_status

    return get_github_copilot_login_status


def _xai_status_loader() -> Callable[[], WebUIOAuthToken | None]:
    from nanobot.providers.xai_oauth import get_xai_oauth_login_status

    return get_xai_oauth_login_status


def _codex_login(context: _LoginContext) -> _PendingLogin:
    with _oauth_cli_kit_import():
        from nanobot.providers.openai_codex_oauth import OpenAICodexOAuthLoginFlow

    return _PendingLogin(OpenAICodexOAuthLoginFlow(
        proxy=context.proxy("openai_codex"),
        timeout_s=_WEBUI_OAUTH_TIMEOUT_S,
        open_browser=not context.remote_browser(),
    ))


def _copilot_login(context: _LoginContext) -> _PendingLogin:
    with _oauth_cli_kit_import():
        from nanobot.providers.github_copilot_oauth import GitHubCopilotOAuthFlow

    # Replace even an existing sign-in: its token might have been revoked.
    context.oauth_flows.clear("github_copilot")
    flow = GitHubCopilotOAuthFlow()
    return _PendingLogin(flow, lambda: flow.user_code)


def _xai_login_failure(exc: Exception) -> str:
    return f"xAI OAuth login failed: {exc}"


def _xai_login(context: _LoginContext) -> _PendingLogin:
    from nanobot.providers.xai_oauth import create_xai_oauth_login

    proxy = context.proxy("xai_grok")
    try:
        return _PendingLogin(create_xai_oauth_login(proxy=proxy, timeout_s=_WEBUI_OAUTH_TIMEOUT_S))
    except Exception as exc:
        raise WebUISettingsError(_xai_login_failure(exc), status=502) from exc


def _complete_codex(flow: WebUIOAuthFlow, response: str | None) -> WebUIOAuthToken | None:
    from nanobot.providers.openai_codex_oauth import OpenAICodexOAuthInputError

    try:
        return flow.complete(response)
    except OpenAICodexOAuthInputError as exc:
        raise WebUISettingsError(str(exc), status=400) from exc


def _remove_token_files(token_path: Path) -> None:
    for path in (token_path, token_path.with_suffix(".lock")):
        with suppress(FileNotFoundError):
            path.unlink()


def _codex_logout() -> Callable[[], None]:
    with _oauth_cli_kit_import():
        from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
        from oauth_cli_kit.storage import FileTokenStorage

    return lambda: _remove_token_files(FileTokenStorage(
        token_filename=OPENAI_CODEX_PROVIDER.token_filename,
    ).get_token_path())


def _copilot_logout() -> Callable[[], None]:
    with _oauth_cli_kit_import():
        from nanobot.providers.github_copilot_provider import get_storage

    return lambda: _remove_token_files(get_storage().get_token_path())


def _xai_logout() -> Callable[[], bool]:
    from nanobot.providers.xai_oauth import logout_xai_oauth

    return logout_xai_oauth


_OAUTH_ADAPTERS = {
    "openai_codex": OAuthProviderAdapter(
        completion_input="callback_url",
        load_status=_codex_status_loader,
        create_login=_codex_login,
        prepare_logout=_codex_logout,
        login_failure=lambda exc: f"OpenAI Codex OAuth login failed: {exc}",
        complete=_complete_codex,
        supports_proxy=True,
        allow_refresh_token=True,
    ),
    "github_copilot": OAuthProviderAdapter(
        completion_input="device_code",
        load_status=_copilot_status_loader,
        create_login=_copilot_login,
        prepare_logout=_copilot_logout,
        login_failure=lambda _: "GitHub sign-in failed. Start again.",
        disclose_login_error=False,
    ),
    "xai_grok": OAuthProviderAdapter(
        completion_input="authorization_code",
        load_status=_xai_status_loader,
        create_login=_xai_login,
        prepare_logout=_xai_logout,
        login_failure=_xai_login_failure,
        supports_proxy=True,
        allow_refresh_token=True,
    ),
}


def oauth_provider_adapter(spec: ProviderSpec) -> OAuthProviderAdapter | None:
    return _OAUTH_ADAPTERS.get(spec.name) if spec.is_oauth else None


def oauth_provider_status(spec: ProviderSpec | None) -> dict[str, Any]:
    unconfigured = {"configured": False, "account": None, "expires_at": None, "login_supported": False}
    if spec is None or (adapter := oauth_provider_adapter(spec)) is None:
        return unconfigured
    try:
        loader = adapter.load_status()
    except Exception as exc:
        logger.debug("{} OAuth backend unavailable: {}", spec.name, exc)
        return unconfigured
    token = None
    try:
        token = loader()
    except Exception as exc:
        logger.debug("could not load OAuth token status for {}: {}", spec.name, exc)
    expires_at = getattr(token, "expires", None) if token else None
    now_ms = int(time.time() * 1000)
    valid_expiry = bool(expires_at and expires_at > now_ms)
    has_refresh = bool(adapter.allow_refresh_token and getattr(token, "refresh", None))
    return {
        "configured": bool(token and token.access and (has_refresh or valid_expiry)),
        "account": getattr(token, "account_id", None) if token else None,
        "expires_at": expires_at,
        "login_supported": True,
    }
