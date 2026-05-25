"""OAuth provider status and actions.

The provider registry declares which providers use OAuth. This module owns the
runtime token lookups and login/logout side effects.
"""

from __future__ import annotations

import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from nanobot.providers.registry import ProviderSpec


@dataclass(frozen=True)
class OAuthProviderError(RuntimeError):
    message: str
    status: int = 400


def _oauth_provider_name(spec: ProviderSpec) -> str:
    return spec.oauth_provider or spec.name


def oauth_provider_status(spec: ProviderSpec) -> dict[str, Any]:
    if not getattr(spec, "is_oauth", False):
        return {"configured": False, "account": None, "expires_at": None, "login_supported": False}

    provider = _oauth_provider_name(spec)
    if provider == "openai_codex":
        try:
            from oauth_cli_kit import get_token as get_codex_token
        except Exception:
            return {
                "configured": False,
                "account": None,
                "expires_at": None,
                "login_supported": False,
            }
        token = None
        with suppress(Exception):
            token = get_codex_token()
        expires_at = getattr(token, "expires", None) if token else None
        return {
            "configured": bool(token and token.access),
            "account": getattr(token, "account_id", None) if token else None,
            "expires_at": expires_at,
            "login_supported": True,
        }

    if provider == "github_copilot":
        try:
            from nanobot.providers.github_copilot_provider import get_github_copilot_login_status
        except Exception:
            return {
                "configured": False,
                "account": None,
                "expires_at": None,
                "login_supported": False,
            }
        token = None
        with suppress(Exception):
            token = get_github_copilot_login_status()
        return {
            "configured": bool(token and token.access and token.expires > int(time.time() * 1000)),
            "account": getattr(token, "account_id", None) if token else None,
            "expires_at": getattr(token, "expires", None) if token else None,
            "login_supported": True,
        }

    return {"configured": False, "account": None, "expires_at": None, "login_supported": False}


def login_oauth_provider(spec: ProviderSpec) -> None:
    provider = _oauth_provider_name(spec)
    if provider == "openai_codex":
        try:
            from oauth_cli_kit import get_token, login_oauth_interactive
        except ImportError:
            raise OAuthProviderError("oauth_cli_kit is not installed", status=500) from None

        token = None
        with suppress(Exception):
            token = get_token()
        if not (token and token.access):
            messages: list[str] = []
            token = login_oauth_interactive(
                print_fn=lambda message: messages.append(str(message)),
                prompt_fn=lambda _prompt: "",
            )
        if not (token and token.access):
            raise OAuthProviderError("OAuth login failed", status=401)
        return

    if provider == "github_copilot":
        try:
            from nanobot.providers.github_copilot_provider import (
                get_github_copilot_login_status,
                login_github_copilot,
            )
        except ImportError:
            raise OAuthProviderError("GitHub Copilot OAuth support is unavailable", status=500) from None

        token = get_github_copilot_login_status()
        if not token:
            token = login_github_copilot(print_fn=lambda _message: None)
        if not (token and token.access):
            raise OAuthProviderError("OAuth login failed", status=401)
        return

    raise OAuthProviderError("OAuth login is not supported for this provider")


def logout_oauth_provider(spec: ProviderSpec) -> None:
    provider = _oauth_provider_name(spec)
    if provider == "openai_codex":
        try:
            from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
            from oauth_cli_kit.storage import FileTokenStorage
        except ImportError:
            raise OAuthProviderError("oauth_cli_kit is not installed", status=500) from None
        token_path = FileTokenStorage(token_filename=OPENAI_CODEX_PROVIDER.token_filename).get_token_path()
    elif provider == "github_copilot":
        try:
            from nanobot.providers.github_copilot_provider import get_storage
        except ImportError:
            raise OAuthProviderError("GitHub Copilot OAuth support is unavailable", status=500) from None
        token_path = get_storage().get_token_path()
    else:
        raise OAuthProviderError("OAuth logout is not supported for this provider")

    for path in (token_path, token_path.with_suffix(".lock")):
        with suppress(FileNotFoundError):
            path.unlink()
