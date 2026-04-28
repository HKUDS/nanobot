"""nanobot auth command: device flow + auth_key authentication."""

from __future__ import annotations

import time
import webbrowser

import httpx
from loguru import logger
from rich.console import Console

from nanobot.auth import AuthInfo, delete_auth, load_auth, save_auth
from nanobot.config.loader import load_config, save_config

console = Console()

DEFAULT_SERVER_URL = "http://127.0.0.1:18791"


def _write_provider_config(token: str, server_url: str) -> None:
    """Write token, server URL, and set nanobot as default provider."""
    config = load_config()
    config.providers.nanobot.api_key = token
    config.providers.nanobot.api_base = f"{server_url}/v1"

    # Switch default provider to nanobot so `nanobot agent` works directly
    config.agents.defaults.provider = "nanobot"

    # Fetch the server's default model name
    try:
        resp = httpx.get(
            f"{server_url}/v1/models",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        models = resp.json().get("data", [])
        if models:
            config.agents.defaults.model = models[0]["id"]
        else:
            console.print("[yellow]Warning: server returned no models. Default model not updated.[/yellow]")
    except httpx.HTTPStatusError as e:
        console.print(f"[yellow]Warning: failed to fetch models from server ({e.response.status_code}). Default model not updated.[/yellow]")
    except httpx.ConnectError:
        console.print(f"[yellow]Warning: cannot reach server to fetch models. Default model not updated.[/yellow]")

    save_config(config)
    logger.debug(f"Updated config: providers.nanobot -> {server_url}")


def cmd_auth(
    auth_key: str | None = None,
    server_url: str | None = None,
    status: bool = False,
    logout: bool = False,
) -> None:
    """Execute the auth command."""
    if logout:
        _cmd_logout()
        return
    if status:
        _cmd_status()
        return
    if auth_key:
        _cmd_auth_key(auth_key, server_url)
        return
    _cmd_device_flow(server_url)


def _cmd_status() -> None:
    """Show current auth status."""
    info = load_auth()
    if not info:
        console.print("[yellow]Not authenticated.[/yellow]  Run [cyan]nanobot auth[/cyan] to sign in.")
        return
    # Verify token is still valid
    try:
        resp = httpx.get(
            f"{info.server_url}/auth/verify",
            headers={"Authorization": f"Bearer {info.token}"},
            timeout=10,
        )
        data = resp.json()
        if data.get("valid"):
            console.print(f"[green]✓ Authenticated[/green]  Server: {info.server_url}")
        else:
            console.print("[red]✗ Token invalid or expired[/red]  Run [cyan]nanobot auth[/cyan] to re-authenticate.")
    except httpx.ConnectError:
        console.print(f"[yellow]? Cannot reach server {info.server_url}[/yellow]  Token saved locally but unverified.")


def _cmd_logout() -> None:
    """Remove saved auth."""
    if delete_auth():
        console.print("[green]✓ Logged out[/green]")
    else:
        console.print("[yellow]Not logged in[/yellow]")


def _cmd_auth_key(key: str, server_url: str | None = None) -> None:
    """Authenticate with a pre-generated auth key."""
    url = server_url or DEFAULT_SERVER_URL

    if not key.startswith("nb_"):
        console.print("[red]Invalid auth key format. Expected 'nb_...' prefix.[/red]")
        raise SystemExit(1)

    # Verify key
    try:
        resp = httpx.get(
            f"{url}/auth/verify",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        data = resp.json()
        if not data.get("valid"):
            console.print("[red]✗ Auth key is invalid or expired[/red]")
            raise SystemExit(1)
    except httpx.ConnectError:
        console.print(f"[red]Cannot reach server at {url}[/red]")
        raise SystemExit(1)

    save_auth(AuthInfo(token=key, server_url=url))
    _write_provider_config(key, url)
    console.print(f"[green]✓ Authenticated[/green]  Server: {url}")


def _cmd_device_flow(server_url: str | None = None) -> None:
    """Run the OAuth Device Flow."""
    url = server_url or DEFAULT_SERVER_URL

    # Step 1: Request device code
    try:
        resp = httpx.post(f"{url}/auth/device/code", timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except httpx.ConnectError:
        console.print(f"[red]Cannot reach server at {url}[/red]")
        raise SystemExit(1)

    device_code = data["device_code"]
    user_code = data["user_code"]
    verification_uri = data["verification_uri"]
    interval = data.get("interval", 5)
    expires_in = data.get("expires_in", 900)

    # Step 2: Open browser or display URL
    full_url = f"{verification_uri}?code={user_code}"
    opened = webbrowser.open(full_url)

    if opened:
        console.print(f"[cyan]Browser opened. Confirm authorization in the browser.[/cyan]")
    else:
        console.print(f"[cyan]Open this URL in your browser:[/cyan]")
        console.print(f"  {full_url}")
    console.print(f"  Code: [bold]{user_code}[/bold]")

    # Step 3: Poll for token
    deadline = time.time() + expires_in
    with console.status("Waiting for authorization..."):
        while time.time() < deadline:
            time.sleep(interval)
            try:
                resp = httpx.post(
                    f"{url}/auth/device/token",
                    json={"device_code": device_code},
                    timeout=10,
                )
                if resp.status_code == 200:
                    token_data = resp.json()
                    token = token_data["token"]
                    expires_at = token_data.get("expires_at")

                    save_auth(AuthInfo(token=token, server_url=url, expires_at=expires_at))
                    _write_provider_config(token, url)
                    console.print(f"[green]✓ Authenticated[/green]  Server: {url}")
                    return
                # 429 = still pending, keep polling
            except httpx.ConnectError:
                console.print("[red]Lost connection to server[/red]")
                raise SystemExit(1)

    console.print("[red]✗ Authorization timed out[/red]  Please try again.")
    raise SystemExit(1)
