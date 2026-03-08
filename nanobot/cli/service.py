"""System service management for nanobot (Linux systemd)."""

import os
import platform
import shutil
import subprocess
from pathlib import Path

from rich.console import Console
from rich.table import Table
import typer

from nanobot import __logo__

console = Console()

# Service name constant - can be parameterized later for multi-instance support
SERVICE_NAME = "nanobot"
SERVICE_DESCRIPTION = "Nanobot AI Assistant Gateway"

# Paths
SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"


def get_service_file_path() -> Path:
    """Get the systemd service file path."""
    return SYSTEMD_USER_DIR / f"{SERVICE_NAME}.service"


def get_nanobot_executable() -> str:
    """Get the path to the nanobot executable."""
    # Try to find nanobot in PATH
    nanobot_path = shutil.which("nanobot")
    if nanobot_path:
        return nanobot_path

    # Fallback: use python -m nanobot
    python_path = shutil.which("python3") or shutil.which("python")
    if python_path:
        return f"{python_path} -m nanobot"

    raise RuntimeError("Cannot find nanobot executable")


def generate_service_unit() -> str:
    """Generate systemd service unit content."""
    try:
        exec_path = get_nanobot_executable()
    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    # Check if it's a simple path or needs shell invocation
    if " " in exec_path:
        # python -m nanobot style - needs shell
        exec_start = f"/bin/bash -c '{exec_path} gateway'"
    else:
        exec_start = f"{exec_path} gateway"

    return f"""[Unit]
Description={SERVICE_DESCRIPTION}
After=network.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""


def check_linux_systemd() -> bool:
    """Check if we're on Linux with systemd available."""
    if platform.system() != "Linux":
        console.print("[red]Error: Service management is only supported on Linux.[/red]")
        return False

    # Check if systemctl exists
    if not shutil.which("systemctl"):
        console.print("[red]Error: systemctl not found. Is systemd installed?[/red]")
        return False

    return True


def run_systemctl_user(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a systemctl --user command."""
    cmd = ["systemctl", "--user"] + args
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def check_linger_enabled() -> bool:
    """Check if linger is enabled for the current user."""
    user = os.environ.get("USER", "")
    if not user:
        return False

    linger_file = Path(f"/var/lib/systemd/linger/{user}")
    return linger_file.exists()


def install_service() -> None:
    """Install nanobot as a systemd user service."""
    if not check_linux_systemd():
        raise typer.Exit(1)

    service_path = get_service_file_path()

    # Check if already installed
    if service_path.exists():
        console.print(f"[yellow]Service already installed at {service_path}[/yellow]")
        if not typer.confirm("Reinstall?"):
            return

    # Create systemd user directory
    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)

    # Generate and write service file
    service_content = generate_service_unit()
    service_path.write_text(service_content)
    console.print(f"[green]✓[/green] Created service file: {service_path}")

    # Reload systemd
    console.print("Reloading systemd daemon...")
    try:
        run_systemctl_user(["daemon-reload"])
        console.print("[green]✓[/green] Daemon reloaded")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Failed to reload daemon: {e.stderr}[/red]")
        raise typer.Exit(1)

    # Enable and start service
    console.print("Enabling and starting service...")
    try:
        run_systemctl_user(["enable", "--now", SERVICE_NAME])
        console.print(f"[green]✓[/green] Service '{SERVICE_NAME}' enabled and started")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Failed to enable/start service: {e.stderr}[/red]")
        raise typer.Exit(1)

    # Check linger
    if not check_linger_enabled():
        console.print()
        console.print("[yellow]⚠ Linger is not enabled.[/yellow]")
        console.print("  Without linger, the service will stop when you log out.")
        console.print(f"  To enable linger, run: [cyan]loginctl enable-linger $USER[/cyan]")
    else:
        console.print("[green]✓[/green] Linger is enabled (service will run at boot)")

    console.print()
    console.print(f"{__logo__} Service installed successfully!")
    console.print(f"  Check status: [cyan]nanobot service status[/cyan]")
    console.print(f"  View logs:    [cyan]nanobot service logs[/cyan]")


def uninstall_service() -> None:
    """Uninstall the nanobot systemd user service."""
    if not check_linux_systemd():
        raise typer.Exit(1)

    service_path = get_service_file_path()

    if not service_path.exists():
        console.print(f"[yellow]Service not installed (no file at {service_path})[/yellow]")

        # Try to disable anyway in case it's registered but file is missing
        try:
            run_systemctl_user(["disable", SERVICE_NAME], check=False)
            run_systemctl_user(["stop", SERVICE_NAME], check=False)
        except Exception:
            pass
        return

    # Stop and disable
    console.print("Stopping and disabling service...")
    try:
        run_systemctl_user(["stop", SERVICE_NAME], check=False)
        run_systemctl_user(["disable", SERVICE_NAME], check=False)
        console.print("[green]✓[/green] Service stopped and disabled")
    except subprocess.CalledProcessError as e:
        console.print(f"[yellow]Warning: {e.stderr}[/yellow]")

    # Remove service file
    service_path.unlink()
    console.print(f"[green]✓[/green] Removed service file: {service_path}")

    # Reload daemon
    try:
        run_systemctl_user(["daemon-reload"])
        console.print("[green]✓[/green] Daemon reloaded")
    except subprocess.CalledProcessError as e:
        console.print(f"[yellow]Warning: Failed to reload daemon: {e.stderr}[/yellow]")

    console.print()
    console.print(f"{__logo__} Service uninstalled.")


def service_status() -> None:
    """Show the status of the nanobot service."""
    if not check_linux_systemd():
        raise typer.Exit(1)

    service_path = get_service_file_path()

    # Check if service file exists
    if not service_path.exists():
        console.print(f"[yellow]Service not installed[/yellow]")
        console.print(f"  Run [cyan]nanobot service install[/cyan] to install")
        return

    # Get service status
    result = run_systemctl_user(["status", SERVICE_NAME], check=False)

    # Also check is-active and is-enabled
    active_result = run_systemctl_user(["is-active", SERVICE_NAME], check=False)
    enabled_result = run_systemctl_user(["is-enabled", SERVICE_NAME], check=False)

    is_active = active_result.returncode == 0
    is_enabled = enabled_result.returncode == 0
    linger_enabled = check_linger_enabled()

    # Display status table
    table = Table(title=f"{SERVICE_NAME} Service Status")
    table.add_column("Property", style="cyan")
    table.add_column("Value")

    table.add_row("Service File", str(service_path))
    table.add_row("Active", "[green]active[/green]" if is_active else "[red]inactive[/red]")
    table.add_row("Enabled", "[green]yes[/green]" if is_enabled else "[dim]no[/dim]")
    table.add_row("Linger", "[green]enabled[/green]" if linger_enabled else "[yellow]disabled[/yellow]")

    console.print(table)

    # Show last few log lines if active
    if is_active:
        console.print()
        console.print("[dim]Recent logs:[/dim]")
        logs_result = subprocess.run(
            ["journalctl", "--user", "-u", SERVICE_NAME, "-n", "5", "--no-pager"],
            capture_output=True,
            text=True,
        )
        if logs_result.stdout.strip():
            for line in logs_result.stdout.strip().split("\n"):
                console.print(f"  [dim]{line}[/dim]")


def service_logs(follow: bool = False, lines: int = 50) -> None:
    """View nanobot service logs."""
    if not check_linux_systemd():
        raise typer.Exit(1)

    service_path = get_service_file_path()
    if not service_path.exists():
        console.print(f"[yellow]Service not installed[/yellow]")
        raise typer.Exit(1)

    cmd = ["journalctl", "--user", "-u", SERVICE_NAME, "-n", str(lines)]
    if follow:
        cmd.append("-f")

    # Use exec to replace current process for follow mode
    if follow:
        os.execvp("journalctl", cmd)
    else:
        subprocess.run(cmd)


def restart_service() -> None:
    """Restart the nanobot service."""
    if not check_linux_systemd():
        raise typer.Exit(1)

    service_path = get_service_file_path()
    if not service_path.exists():
        console.print(f"[red]Service not installed[/red]")
        raise typer.Exit(1)

    try:
        run_systemctl_user(["restart", SERVICE_NAME])
        console.print(f"[green]✓[/green] Service restarted")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Failed to restart service: {e.stderr}[/red]")
        raise typer.Exit(1)


# Create typer app for service commands
app = typer.Typer(help="Manage nanobot system service (Linux)")

app.command(name="install")(install_service)
app.command(name="uninstall")(uninstall_service)
app.command(name="status")(service_status)


@app.command(name="logs")
def logs_cmd(
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
):
    """View nanobot service logs."""
    service_logs(follow=follow, lines=lines)


@app.command(name="restart")
def restart_cmd():
    """Restart the nanobot service."""
    restart_service()
