"""Run the shared terminal client on a gateway through an existing SSH route."""

from __future__ import annotations

import ipaddress
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import typer


def _ssh_path(path: Path) -> str:
    value = str(path.expanduser().absolute())
    if any(ord(character) < 32 for character in value):
        raise ValueError("SSH file paths cannot contain control characters")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def remote_command(
    *, host: str, network: str, user: str, identity: Path, known_hosts: Path,
    port: int = 22, executable: str = "nanobot", config: str | None = None,
    stream: str = "main", theme: str = "auto",
) -> list[str]:
    address = ipaddress.ip_address(host)
    route = ipaddress.ip_network(network, strict=False)
    if (address not in route or address.is_loopback or address.is_multicast
            or address.is_unspecified or route.prefixlen == 0 or "%" in host):
        raise ValueError("gateway address must be inside the explicit existing WireGuard network")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}", user) is None or not 1 <= port <= 65535:
        raise ValueError("invalid SSH user or port")
    if stream not in {"main", "notifications"} or theme not in {"auto", "dark", "light"}:
        raise ValueError("invalid conversation or theme")
    for path in (identity, known_hosts):
        if not path.expanduser().is_file():
            raise ValueError("SSH identity and verified known-hosts file must already exist")
    if (not executable or executable.startswith("-")
            or any(ord(character) < 32 for value in (executable, config or "") for character in value)):
        raise ValueError("invalid remote command or configuration path")
    if config is not None and not config.startswith("/"):
        raise ValueError("remote configuration must use an absolute path on the gateway")
    ssh = shutil.which("ssh")
    if ssh is None:
        raise ValueError("OpenSSH client is not installed")
    command = [executable, "agent", "--session", "websocket:shared-" + stream, "--theme", theme]
    if config is not None:
        command.extend(["--config", config])
    # Disable ambient SSH configuration, proxies, forwarding and password fallback.
    # The TUI runs on the gateway, so bootstrap stays local to that machine.
    options = [
        "BatchMode=yes", "StrictHostKeyChecking=yes", "CheckHostIP=yes", "IdentitiesOnly=yes",
        "PasswordAuthentication=no", "KbdInteractiveAuthentication=no", "ForwardAgent=no",
        "ForwardX11=no", "ClearAllForwardings=yes", "ControlMaster=no", "ControlPath=none",
        "ServerAliveInterval=30", "ServerAliveCountMax=3", "ConnectTimeout=10",
        "ConnectionAttempts=1", "EscapeChar=none", "IdentityFile=" + _ssh_path(identity),
        "UserKnownHostsFile=" + _ssh_path(known_hosts), "GlobalKnownHostsFile=" + _ssh_path(Path(os.devnull)),
    ]
    argv = [ssh, "-F", os.devnull, "-tt", "-p", str(port), "-l", user]
    for option in options:
        argv.extend(["-o", option])
    return [*argv, "--", str(address), shlex.join(command)]


def remote(
    host: str = typer.Option(..., help="Gateway IP reachable through the existing WireGuard route"),
    network: str = typer.Option(..., help="Existing WireGuard address range in CIDR form"),
    user: str = typer.Option(..., help="SSH user on the gateway"),
    identity: Path = typer.Option(..., help="Local private-key path; its contents are never copied"),
    known_hosts: Path = typer.Option(..., help="Existing known_hosts file with a verified gateway key"),
    port: int = typer.Option(22, min=1, max=65535),
    executable: str = typer.Option("nanobot", help="nanobot executable on the gateway"),
    config: str | None = typer.Option(None, help="Absolute config path on the gateway"),
    stream: str = typer.Option("main", help="main or notifications"),
    theme: str = typer.Option("auto", help="auto, dark or light"),
    dry_run: bool = typer.Option(False, help="Show the command without connecting"),
) -> None:
    """Open the gateway's TUI through SSH without creating another tunnel."""
    try:
        command = remote_command(host=host, network=network, user=user, identity=identity,
                                 known_hosts=known_hosts, port=port, executable=executable,
                                 config=config, stream=stream, theme=theme)
        if dry_run:
            typer.echo(shlex.join(command))
            return
        # A disconnected terminal is never silently rerun on this device. Shared
        # history and durable goals remain on the gateway for the next connection.
        result = subprocess.run(command, check=False)
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    raise typer.Exit(result.returncode)
