"""Authentication management commands."""

import asyncio
from typing import Any

import typer
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt

from nanobot.auth import ClaudeOAuthManager

app = typer.Typer(help="Manage OAuth authentication")
console = Console()


@app.command()
def list_profiles():
    """List all authentication profiles."""

    async def _list():
        oauth_manager = ClaudeOAuthManager()
        profiles = await oauth_manager.list_profiles()

        if not profiles:
            console.print("[yellow]No authentication profiles found.[/yellow]")
            console.print("Use 'nanobot auth add' to add OAuth credentials.")
            return

        table = Table(title="Authentication Profiles")
        table.add_column("Profile ID", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Provider", style="green")
        table.add_column("Email", style="blue")
        table.add_column("Status", style="bold")
        table.add_column("Expires At", style="dim")

        for profile_id, info in profiles.items():
            status = "[green]✓ Valid[/green]" if info.get("valid", False) else "[red]✗ Expired[/red]"
            expires_at = info.get("expires_at", "N/A")
            if expires_at != "N/A":
                expires_at = expires_at.split("T")[0]  # Show date only

            table.add_row(
                profile_id,
                info["type"],
                info["provider"],
                info.get("email", ""),
                status,
                expires_at,
            )

        console.print(table)

    asyncio.run(_list())


@app.command()
def add(
    profile_id: str = typer.Option(..., "--profile", "-p", help="Profile ID (e.g., anthropic:default)"),
    access_token: str = typer.Option(None, "--access", help="Access token"),
    refresh_token: str = typer.Option(None, "--refresh", help="Refresh token"),
    expires_in: int = typer.Option(3600, "--expires", help="Expires in seconds (default: 3600)"),
    email: str = typer.Option(None, "--email", help="User email"),
    provider: str = typer.Option("anthropic", "--provider", help="Provider name"),
):
    """Add OAuth credentials."""

    # Prompt for missing values
    if not access_token:
        access_token = Prompt.ask("Access token", password=True)

    if not refresh_token:
        refresh_token = Prompt.ask("Refresh token", password=True)

    if not email:
        email = Prompt.ask("Email (optional)", default="")
        if not email:
            email = None

    async def _add():
        oauth_manager = ClaudeOAuthManager()
        await oauth_manager.add_oauth_credentials(
            profile_id=profile_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            email=email,
            provider=provider,
        )
        console.print(f"[green]✓[/green] Added OAuth credentials for [cyan]{profile_id}[/cyan]")

    asyncio.run(_add())


@app.command()
def remove(
    profile_id: str = typer.Argument(..., help="Profile ID to remove"),
):
    """Remove authentication profile."""

    async def _remove():
        oauth_manager = ClaudeOAuthManager()
        success = await oauth_manager.remove_profile(profile_id)

        if success:
            console.print(f"[green]✓[/green] Removed profile [cyan]{profile_id}[/cyan]")
        else:
            console.print(f"[red]✗[/red] Profile [cyan]{profile_id}[/cyan] not found")

    asyncio.run(_remove())


@app.command()
def test(
    profile_id: str = typer.Option("anthropic:default", "--profile", "-p", help="Profile ID to test"),
):
    """Test authentication for a profile."""

    async def _test():
        oauth_manager = ClaudeOAuthManager()

        console.print(f"Testing authentication for [cyan]{profile_id}[/cyan]...")

        api_key = await oauth_manager.get_api_key_for_profile(profile_id)

        if api_key:
            # Mask the API key for display
            masked = api_key[:15] + "..." + api_key[-8:] if len(api_key) > 23 else api_key
            console.print(f"[green]✓[/green] Authentication successful!")
            console.print(f"API Key: [dim]{masked}[/dim]")
        else:
            console.print(f"[red]✗[/red] Authentication failed")
            console.print("Check if the profile exists and tokens are valid")

    asyncio.run(_test())


@app.command()
def refresh(
    profile_id: str = typer.Option("anthropic:default", "--profile", "-p", help="Profile ID to refresh"),
):
    """Force refresh tokens for a profile."""

    async def _refresh():
        oauth_manager = ClaudeOAuthManager()

        console.print(f"Refreshing tokens for [cyan]{profile_id}[/cyan]...")

        # Force refresh by calling internal method
        result = await oauth_manager._refresh_if_needed(profile_id)

        if result:
            console.print(f"[green]✓[/green] Token refresh successful!")
            console.print(f"Expires at: [dim]{result.expires_at.isoformat()}[/dim]")
        else:
            console.print(f"[red]✗[/red] Token refresh failed")

    asyncio.run(_refresh())


@app.command()
def setup():
    """Interactive OAuth setup guide."""
    console.print("[bold cyan]Claude OAuth Setup Guide[/bold cyan]")
    console.print("")
    console.print("To get OAuth tokens for Claude:")
    console.print("")
    console.print("1. Open [link=https://console.anthropic.com]https://console.anthropic.com[/link]")
    console.print("2. Sign in to your account")
    console.print("3. Go to 'API Keys' or 'OAuth Apps'")
    console.print("4. Create a new OAuth application")
    console.print("5. Copy the access_token and refresh_token")
    console.print("")
    console.print("Then run:")
    console.print("[dim]nanobot auth add --profile anthropic:default[/dim]")
    console.print("")
    console.print("[yellow]Note: OAuth implementation requires proper client_id from Anthropic.[/yellow]")


if __name__ == "__main__":
    app()