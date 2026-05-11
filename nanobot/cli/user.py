"""CLI: ``nanobot user …`` operator subcommands.

Wraps :class:`nanobot.auth.service.AuthService` so a sysadmin can manage
WebUI accounts without the gateway being up. Each command writes an
audit_log row with ``actor_user_id=None`` (system actor).
"""

from __future__ import annotations

import getpass
import sys
from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from nanobot.auth import AuthError, AuthService, EmailTakenError

user_app = typer.Typer(
    name="user",
    help="Manage WebUI user accounts (create, list, promote, demote, reset, delete).",
    no_args_is_help=True,
)
console = Console()


def _service() -> AuthService:
    return AuthService.default()


def _format_ts(epoch: int | None) -> str:
    if not epoch:
        return "-"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _prompt_password() -> str:
    pwd = getpass.getpass("Password (input hidden): ")
    confirm = getpass.getpass("Confirm password: ")
    if pwd != confirm:
        console.print("[red]Passwords do not match.[/red]")
        raise typer.Exit(1)
    return pwd


@user_app.command("list")
def list_users() -> None:
    """List all WebUI users."""
    svc = _service()
    try:
        rows = svc._conn.execute(  # noqa: SLF001 — operator tooling reads directly
            "SELECT id, email, role, display_name, created_at, last_login_at, disabled "
            "FROM users ORDER BY created_at"
        ).fetchall()
    finally:
        svc.close()
    if not rows:
        console.print("[dim]No users.[/dim]")
        return
    table = Table(show_lines=False, header_style="bold")
    table.add_column("ID")
    table.add_column("Email")
    table.add_column("Role")
    table.add_column("Display name")
    table.add_column("Created")
    table.add_column("Last login")
    table.add_column("Disabled")
    for r in rows:
        table.add_row(
            r["id"],
            r["email"],
            r["role"],
            r["display_name"] or "-",
            _format_ts(r["created_at"]),
            _format_ts(r["last_login_at"]),
            "yes" if r["disabled"] else "no",
        )
    console.print(table)


@user_app.command("create")
def create_user(
    email: str = typer.Argument(..., help="Email address (case-insensitive)."),
    role: str = typer.Option(
        "user", "--role", "-r", help="Role: 'user' or 'admin'."
    ),
    display_name: Optional[str] = typer.Option(
        None, "--display-name", "-n", help="Optional display name."
    ),
) -> None:
    """Create a new WebUI account."""
    if role not in ("user", "admin"):
        console.print(f"[red]Invalid role '{role}'. Use 'user' or 'admin'.[/red]")
        raise typer.Exit(1)
    password = _prompt_password()
    svc = _service()
    try:
        user = svc.create_user(email, password, display_name=display_name, role=role)
    except EmailTakenError:
        console.print(f"[red]Email '{email}' is already registered.[/red]")
        raise typer.Exit(1) from None
    except AuthError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
    finally:
        svc.close()
    console.print(f"[green]Created[/green] {user.email} (id={user.id}, role={user.role})")


def _resolve_user_id(svc: AuthService, identifier: str) -> str:
    """Accept either email or ULID; return the canonical ULID."""
    user = svc.get_user_by_email(identifier)
    if user is not None:
        return user.id
    try:
        return svc.get_user(identifier).id
    except (AuthError, ValueError):
        console.print(f"[red]No user matches '{identifier}'.[/red]")
        raise typer.Exit(1) from None


def _set_role(identifier: str, target_role: str, event: str) -> None:
    svc = _service()
    try:
        user_id = _resolve_user_id(svc, identifier)
        svc._conn.execute("UPDATE users SET role = ? WHERE id = ?", (target_role, user_id))
        svc._audit(event, target_user_id=user_id)
        user = svc.get_user(user_id)
        console.print(
            f"[green]{event}[/green] {user.email} → role={user.role}"
        )
    finally:
        svc.close()


@user_app.command("promote")
def promote(identifier: str = typer.Argument(..., help="Email or user ID.")) -> None:
    """Grant admin role to a user."""
    _set_role(identifier, "admin", "promote")


@user_app.command("demote")
def demote(identifier: str = typer.Argument(..., help="Email or user ID.")) -> None:
    """Revoke admin role; user becomes a regular user."""
    _set_role(identifier, "user", "demote")


@user_app.command("reset-password")
def reset_password(identifier: str = typer.Argument(..., help="Email or user ID.")) -> None:
    """Set a new password and revoke all of the user's active sessions."""
    password = _prompt_password()
    svc = _service()
    try:
        user_id = _resolve_user_id(svc, identifier)
        try:
            svc.set_password(user_id, password)
        except AuthError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from None
        user = svc.get_user(user_id)
        console.print(f"[green]Password reset[/green] for {user.email}; sessions revoked.")
    finally:
        svc.close()


@user_app.command("delete")
def delete(
    identifier: str = typer.Argument(..., help="Email or user ID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Delete a user account and all of its sessions.

    The on-disk per-user directory ``~/.nanobot/users/<id>`` is NOT removed
    automatically — an operator should clean it up manually after auditing
    the contents.
    """
    svc = _service()
    try:
        user_id = _resolve_user_id(svc, identifier)
        user = svc.get_user(user_id)
        if not yes:
            confirm = typer.confirm(
                f"Delete account {user.email} (id={user.id})?",
                default=False,
            )
            if not confirm:
                console.print("[yellow]Aborted.[/yellow]")
                raise typer.Exit(0)
        svc._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        svc._audit("delete", target_user_id=user_id, detail=user.email)
        console.print(
            f"[green]Deleted[/green] {user.email}. Filesystem data under "
            f"~/.nanobot/users/{user.id}/ is preserved; remove manually if appropriate."
        )
    finally:
        svc.close()


@user_app.command("disable")
def disable(
    identifier: str = typer.Argument(..., help="Email or user ID."),
    on: bool = typer.Option(True, "--on/--off", help="Set the disabled flag."),
) -> None:
    """Disable (or re-enable) a user account without deleting it."""
    svc = _service()
    try:
        user_id = _resolve_user_id(svc, identifier)
        svc._conn.execute("UPDATE users SET disabled = ? WHERE id = ?", (1 if on else 0, user_id))
        if on:
            # Revoke any live sessions on disable.
            svc.revoke_all_sessions(user_id)
        event = "disable" if on else "enable"
        svc._audit(event, target_user_id=user_id)
        user = svc.get_user(user_id)
        console.print(f"[green]{event}d[/green] {user.email}")
    finally:
        svc.close()


if __name__ == "__main__":  # pragma: no cover
    user_app(sys.argv[1:])
