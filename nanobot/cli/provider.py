"""Typer commands for OAuth provider authentication."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import typer
from rich.console import Console

from nanobot import __logo__
from nanobot.providers.oauth_guidance import OAUTH_CLI_KIT_MISSING_MESSAGE

if TYPE_CHECKING:
    from nanobot.providers.registry import ProviderSpec


console = Console()
provider_app = typer.Typer(help="Manage providers")

_PROVIDER_DISPLAY: dict[str, str] = {
    "openai_codex": "OpenAI Codex",
    "xai_grok": "xAI Grok",
    "github_copilot": "GitHub Copilot",
}

_OAUTH_PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "openai_codex": "openai-codex/gpt-5.6-sol",
    "xai_grok": "xai-grok/grok-4.6",
    "github_copilot": "github-copilot/gpt-5.4-mini",
}


class _OAuthToken(Protocol):
    access: str | None
    account_id: str | None


class _GetOAuthToken(Protocol):
    def __call__(self, *, proxy: str | None = None) -> _OAuthToken | None: ...


class _LoginOAuthInteractive(Protocol):
    def __call__(
        self,
        *,
        print_fn: Callable[[str], None],
        prompt_fn: Callable[[str], str],
        proxy: str | None = None,
    ) -> _OAuthToken | None: ...


class _OAuthProviderConfig(Protocol):
    token_filename: str


class _TokenStorage(Protocol):
    def get_token_path(self) -> Path: ...


class _FileTokenStorageFactory(Protocol):
    def __call__(self, *, token_filename: str) -> _TokenStorage: ...


def _required_module_attribute(module_name: str, attribute: str) -> object:
    """Load an optional dependency attribute with import-compatible errors."""
    module = import_module(module_name)
    try:
        return getattr(module, attribute)
    except AttributeError as exc:
        raise ImportError(f"{module_name}.{attribute} is unavailable") from exc


def _load_openai_oauth_client() -> tuple[_GetOAuthToken, _LoginOAuthInteractive]:
    """Load the untyped OAuth client behind a typed boundary."""
    return (
        cast(_GetOAuthToken, _required_module_attribute("oauth_cli_kit", "get_token")),
        cast(
            _LoginOAuthInteractive,
            _required_module_attribute("oauth_cli_kit", "login_oauth_interactive"),
        ),
    )


def _load_openai_oauth_storage() -> tuple[_OAuthProviderConfig, _FileTokenStorageFactory]:
    """Load the untyped OAuth storage API behind a typed boundary."""
    return (
        cast(
            _OAuthProviderConfig,
            _required_module_attribute(
                "oauth_cli_kit.providers",
                "OPENAI_CODEX_PROVIDER",
            ),
        ),
        cast(
            _FileTokenStorageFactory,
            _required_module_attribute("oauth_cli_kit.storage", "FileTokenStorage"),
        ),
    )


def _resolve_oauth_provider(provider: str) -> ProviderSpec:
    """Resolve and validate an OAuth provider configuration."""
    from nanobot.providers.registry import PROVIDERS

    key = provider.replace("-", "_")
    spec = next((s for s in PROVIDERS if s.name == key and s.is_oauth), None)
    if not spec:
        names = ", ".join(s.name.replace("_", "-") for s in PROVIDERS if s.is_oauth)
        console.print(f"[red]Unknown OAuth provider: {provider}[/red]  Supported: {names}")
        raise typer.Exit(1)
    return spec


def _set_oauth_provider_as_main(
    provider_name: str,
    *,
    model: str | None = None,
    config_path: str | None = None,
) -> None:
    """Persist an OAuth provider as the active agent provider."""
    from nanobot.config.loader import get_config_path, load_config, save_config, set_config_path

    resolved_config_path = Path(config_path).expanduser().resolve() if config_path else None
    if resolved_config_path is not None and get_config_path() != resolved_config_path:
        set_config_path(resolved_config_path)
        console.print(f"[dim]Using config: {resolved_config_path}[/dim]")

    config = load_config(resolved_config_path)
    selected_model = (model or "").strip() or _OAUTH_PROVIDER_DEFAULT_MODELS[provider_name]
    config.agents.defaults.model_preset = None
    config.agents.defaults.provider = provider_name
    config.agents.defaults.model = selected_model
    if provider_name == "xai_grok" and selected_model in {
        "xai-grok/grok-4.5",
        "xai-grok/grok-4.6",
    }:
        config.agents.defaults.context_window_tokens = 500_000
    save_config(config, resolved_config_path)

    saved_path = resolved_config_path or get_config_path()
    console.print(
        f"[green]✓ Set {provider_name.replace('_', '-')} as the main provider[/green]  "
        f"[dim]{selected_model}[/dim]"
    )
    console.print(f"[dim]Saved: {saved_path}[/dim]")


@provider_app.command("login")
def provider_login(
    provider: str = typer.Argument(
        ...,
        help="OAuth provider (e.g. 'openai-codex', 'xai-grok', 'github-copilot')",
    ),
    set_main: bool = typer.Option(
        False,
        "--set-main",
        "--main",
        help="Set this OAuth provider as the active agent provider after login",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Model to use when setting this provider as the active provider",
    ),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Authenticate with an OAuth provider."""
    spec = _resolve_oauth_provider(provider)

    handler = _LOGIN_HANDLERS.get(spec.name)
    if not handler:
        console.print(f"[red]Login not implemented for {spec.label}[/red]")
        raise typer.Exit(1)

    if config:
        from nanobot.config.loader import set_config_path

        resolved_config_path = Path(config).expanduser().resolve()
        set_config_path(resolved_config_path)
        console.print(f"[dim]Using config: {resolved_config_path}[/dim]")

    console.print(f"{__logo__} OAuth Login - {spec.label}\n")
    handler()
    if set_main or model:
        _set_oauth_provider_as_main(spec.name, model=model, config_path=config)


@provider_app.command("logout")
def provider_logout(
    provider: str = typer.Argument(
        ...,
        help="OAuth provider (e.g. 'openai-codex', 'xai-grok', 'github-copilot')",
    ),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Log out from an OAuth provider."""
    spec = _resolve_oauth_provider(provider)

    handler = _LOGOUT_HANDLERS.get(spec.name)
    if not handler:
        console.print(f"[red]Logout not implemented for {spec.label}[/red]")
        raise typer.Exit(1)

    if config:
        from nanobot.config.loader import set_config_path

        resolved_config_path = Path(config).expanduser().resolve()
        set_config_path(resolved_config_path)
        console.print(f"[dim]Using config: {resolved_config_path}[/dim]")

    console.print(f"{__logo__} OAuth Logout - {spec.label}\n")
    handler()


def _login_openai_codex() -> None:
    try:
        from nanobot.config.loader import load_config, resolve_config_env_vars

        get_token, login_oauth_interactive = _load_openai_oauth_client()
        proxy = None
        try:
            proxy = resolve_config_env_vars(load_config()).providers.openai_codex.proxy or None
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e
        token = None
        with suppress(Exception):
            token = get_token(proxy=proxy)
        if not (token and token.access):
            console.print("[cyan]Starting interactive OAuth login...[/cyan]\n")
            token = login_oauth_interactive(
                print_fn=lambda s: console.print(s),
                prompt_fn=lambda s: typer.prompt(s),
                proxy=proxy,
            )
        if not (token and token.access):
            console.print("[red]✗ Authentication failed[/red]")
            raise typer.Exit(1)
        console.print(
            f"[green]✓ Authenticated with OpenAI Codex[/green]  [dim]{token.account_id}[/dim]"
        )
    except ImportError:
        console.print(f"[red]{OAUTH_CLI_KIT_MISSING_MESSAGE}[/red]")
        raise typer.Exit(1)


def _logout_openai_codex() -> None:
    """Clear local OAuth credentials for OpenAI Codex."""
    try:
        provider_config, storage_factory = _load_openai_oauth_storage()
    except ImportError:
        console.print(f"[red]{OAUTH_CLI_KIT_MISSING_MESSAGE}[/red]")
        raise typer.Exit(1)

    storage = storage_factory(token_filename=provider_config.token_filename)
    _delete_oauth_files(storage.get_token_path(), _PROVIDER_DISPLAY["openai_codex"])


def _login_xai_grok() -> None:
    """Authenticate with xAI using the Grok subscription OAuth contract."""
    from nanobot.config.loader import load_config, resolve_config_env_vars
    from nanobot.providers.xai_oauth import get_xai_oauth_token, login_xai_oauth

    try:
        proxy = resolve_config_env_vars(load_config()).providers.xai_grok.proxy or None
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    token = None
    with suppress(Exception):
        token = get_xai_oauth_token(proxy=proxy)
    if not (token and token.access):
        console.print(
            "[cyan]Starting xAI browser sign-in for your X Premium / Grok subscription...[/cyan]\n"
        )
        try:
            token = login_xai_oauth(
                print_fn=lambda message: console.print(message),
                prompt_fn=lambda prompt: typer.prompt(prompt),
                proxy=proxy,
            )
        except Exception as exc:
            console.print(f"[red]Authentication error: {exc}[/red]")
            raise typer.Exit(1) from exc
    account = token.account_id or "xAI account"
    console.print(f"[green]✓ Authenticated with xAI[/green]  [dim]{account}[/dim]")
    console.print(
        "[dim]Hosted X Search is enabled automatically when the selected model supports it.[/dim]"
    )


def _logout_xai_grok() -> None:
    """Clear local xAI OAuth credentials for this nanobot instance."""
    from nanobot.providers.xai_oauth import get_xai_oauth_storage_path, logout_xai_oauth

    token_path = get_xai_oauth_storage_path()
    provider_label = _PROVIDER_DISPLAY["xai_grok"]
    if logout_xai_oauth():
        console.print(f"[green]✓ Logged out from {provider_label}[/green]")
        console.print(f"[dim]Removed: {token_path}[/dim]")
    else:
        console.print(f"[yellow]! No local OAuth credentials found for {provider_label}[/yellow]")


def _logout_github_copilot() -> None:
    """Clear local OAuth credentials for GitHub Copilot."""
    try:
        from nanobot.providers.github_copilot_provider import get_storage
    except ImportError:
        console.print(f"[red]{OAUTH_CLI_KIT_MISSING_MESSAGE}[/red]")
        raise typer.Exit(1)

    storage = get_storage()
    _delete_oauth_files(storage.get_token_path(), _PROVIDER_DISPLAY["github_copilot"])


def _delete_oauth_files(token_path: Path, provider_label: str) -> None:
    """Delete OAuth token and lock files, reporting the result."""
    removed_paths: list[Path] = []
    skipped: list[tuple[Path, OSError]] = []
    for path in (token_path, token_path.with_suffix(".lock")):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            skipped.append((path, exc))
            continue
        removed_paths.append(path)

    if not removed_paths and not skipped:
        console.print(f"[yellow]! No local OAuth credentials found for {provider_label}[/yellow]")
        return

    if removed_paths:
        console.print(f"[green]✓ Logged out from {provider_label}[/green]")
        for path in removed_paths:
            console.print(f"[dim]Removed: {path}[/dim]")
    for path, exc in skipped:
        console.print(f"[yellow]! Could not remove {path}: {exc}[/yellow]")


def _login_github_copilot() -> None:
    try:
        from nanobot.providers.github_copilot_provider import login_github_copilot

        console.print("[cyan]Starting GitHub Copilot device flow...[/cyan]\n")
        token = login_github_copilot(
            print_fn=lambda s: console.print(s),
            prompt_fn=lambda s: typer.prompt(s),
        )
        account = token.account_id or "GitHub"
        console.print(
            f"[green]✓ Authenticated with GitHub Copilot[/green]  [dim]{account}[/dim]"
        )
    except Exception as e:
        console.print(f"[red]Authentication error: {e}[/red]")
        raise typer.Exit(1)


_LOGIN_HANDLERS: dict[str, Callable[[], None]] = {
    "openai_codex": _login_openai_codex,
    "xai_grok": _login_xai_grok,
    "github_copilot": _login_github_copilot,
}
_LOGOUT_HANDLERS: dict[str, Callable[[], None]] = {
    "openai_codex": _logout_openai_codex,
    "xai_grok": _logout_xai_grok,
    "github_copilot": _logout_github_copilot,
}
