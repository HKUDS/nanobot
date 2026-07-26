"""Typer commands for installing and governing extensions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from nanobot.extensions import ExtensionService

ServiceFactory = Callable[[], ExtensionService]


def create_extensions_app(
    *,
    console: Console,
    service_factory: ServiceFactory = ExtensionService,
) -> typer.Typer:
    """Build the extension command group around the transport-neutral service."""
    app = typer.Typer(help="Discover, install, inspect, and govern extensions.")

    def service() -> ExtensionService:
        return service_factory()

    def run(awaitable: Any) -> dict[str, Any]:
        try:
            return asyncio.run(awaitable)
        except (KeyError, RuntimeError, ValueError) as exc:
            console.print(f"[red]Error: {exc}[/red]")
            raise typer.Exit(1) from exc

    @app.command("list")
    def list_extensions() -> None:
        """List installed extensions and their activation policy."""
        payload = run(service().status())
        table = Table(show_header=True, header_style="bold")
        table.add_column("Extension")
        table.add_column("Runtime")
        table.add_column("State")
        table.add_column("Trust")
        table.add_column("Version")
        for item in payload["extensions"]:
            state = "active" if item["active"] else ("enabled" if item["enabled"] else "disabled")
            table.add_row(
                item["name"],
                item["runtime"],
                state,
                "trusted" if item["trusted"] else "untrusted",
                item["version"],
            )
        console.print(table)
        if not payload["extensions"]:
            console.print("[dim]No extensions installed.[/dim]")
        if payload["diagnostics"]:
            console.print(f"[yellow]{len(payload['diagnostics'])} diagnostic(s)[/yellow]")

    @app.command("inspect")
    def inspect_extension(extension_id: str = typer.Argument(..., help="Extension ID")) -> None:
        """Show manifest, dependencies, permissions, and diagnostics."""
        payload = run(service().status())
        item = next(
            (candidate for candidate in payload["extensions"] if candidate["id"] == extension_id),
            None,
        )
        if item is None:
            console.print(f"[red]Extension not found: {extension_id}[/red]")
            raise typer.Exit(1)
        console.print(f"[bold]{item['name']}[/bold] [dim]{item['version']}[/dim]")
        console.print(item["description"] or "[dim]No description.[/dim]")
        console.print(f"Runtime: {item['runtime']}  Scope: {item['scope']}")
        console.print(
            f"State: {'active' if item['active'] else 'inactive'}  "
            f"Trust: {'trusted' if item['trusted'] else 'untrusted'}"
        )
        _print_named_rows(console, "Contributions", item["contributions"], "kind", "name")
        _print_named_rows(console, "Dependencies", item["dependencies"], "kind", "name")
        _print_permissions(console, item["permissions"], set(item["granted_permissions"]))
        diagnostics = [
            diagnostic
            for diagnostic in payload["diagnostics"]
            if diagnostic["extension_id"] == extension_id
        ]
        if diagnostics:
            console.print("\n[bold]Diagnostics[/bold]")
            for diagnostic in diagnostics:
                console.print(
                    f"  [yellow]{diagnostic['code']}[/yellow] {diagnostic['message']}"
                )

    @app.command("search")
    def search_extensions(
        query: str = typer.Argument("", help="Package name or keyword"),
        ecosystem: str = typer.Option(
            "all",
            "--ecosystem",
            "-e",
            help="all, nanobot, pi, or openclaw",
        ),
        limit: int = typer.Option(20, "--limit", min=1, max=100),
    ) -> None:
        """Search compatible extension packages on npm."""
        payload = run(service().search(query, ecosystem=ecosystem, limit=limit))
        table = Table(show_header=True, header_style="bold")
        table.add_column("Package")
        table.add_column("Ecosystem")
        table.add_column("Version")
        table.add_column("Description")
        for package in payload["packages"]:
            table.add_row(
                package["name"],
                package["ecosystem"],
                package["version"],
                package["description"],
            )
        console.print(table)
        if not payload["packages"]:
            console.print("[dim]No compatible packages found.[/dim]")

    @app.command("install")
    def install_extension(
        source: str = typer.Argument(..., help="npm spec, Git URL, or local path"),
        kind: str = typer.Option("npm", "--kind", help="npm, git, or local"),
        ref: str = typer.Option("", "--ref", help="Git branch, tag, or commit"),
    ) -> None:
        """Install an extension without granting trust or permissions."""
        payload = run(service().install(source, kind=kind, ref=ref, trusted=False))
        record = payload["record"]
        console.print(
            f"[green]Installed {record['id']} {record['version']}[/green] "
            "[yellow](untrusted)[/yellow]"
        )
        console.print(
            f"Review with [bold]nanobot extensions inspect {record['id']}[/bold], "
            "then grant permissions and trust it explicitly."
        )

    def policy_command(name: str, value: bool, label: str, help_text: str) -> None:
        @app.command(name, help=help_text)
        def update(extension_id: str = typer.Argument(..., help="Extension ID")) -> None:
            payload = run(
                service().set_enabled(extension_id, value)
                if name in {"enable", "disable"}
                else service().set_trusted(extension_id, value)
            )
            console.print(f"[green]{label}: {payload['record']['id']}[/green]")

    policy_command("enable", True, "Enabled", "Allow an installed extension to activate.")
    policy_command("disable", False, "Disabled", "Prevent an installed extension from activating.")
    policy_command("trust", True, "Trusted", "Trust an installed extension's executable code.")
    policy_command("untrust", False, "Trust revoked", "Revoke trust and stop extension activation.")

    @app.command("permissions")
    def set_permissions(
        extension_id: str = typer.Argument(..., help="Extension ID"),
        permissions: list[str] = typer.Argument(
            None,
            help="Exact permissions to grant; omit all to revoke every grant",
        ),
    ) -> None:
        """Replace the extension's granted host permissions."""
        payload = run(service().set_permissions(extension_id, set(permissions or [])))
        granted = payload["record"]["granted_permissions"]
        console.print(
            f"[green]Updated permissions for {extension_id}:[/green] "
            + (", ".join(granted) if granted else "none")
        )

    @app.command("uninstall")
    def uninstall_extension(
        extension_id: str = typer.Argument(..., help="Extension ID"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    ) -> None:
        """Remove an installed extension."""
        if not yes and not typer.confirm(f"Uninstall extension '{extension_id}'?"):
            raise typer.Abort()
        run(service().uninstall(extension_id))
        console.print(f"[green]Uninstalled {extension_id}[/green]")

    return app


def _print_named_rows(
    console: Console,
    title: str,
    rows: list[dict[str, Any]],
    category_key: str,
    name_key: str,
) -> None:
    console.print(f"\n[bold]{title}[/bold]")
    if not rows:
        console.print("  [dim]None[/dim]")
        return
    for row in rows:
        console.print(f"  {row[category_key]}: {row[name_key]}")


def _print_permissions(
    console: Console,
    permissions: list[dict[str, str]],
    granted: set[str],
) -> None:
    console.print("\n[bold]Permissions[/bold]")
    if not permissions:
        console.print("  [dim]None requested[/dim]")
        return
    for permission in permissions:
        status = "[green]granted[/green]" if permission["name"] in granted else "[yellow]pending[/yellow]"
        reason = f" — {permission['reason']}" if permission["reason"] else ""
        console.print(f"  {permission['name']} ({status}){reason}")
