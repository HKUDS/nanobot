"""Server-console commands for explicit remote WebUI device authorization."""

from __future__ import annotations

import http.client
import ipaddress
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

import typer

from nanobot.config.home import get_home_path

app = typer.Typer(help="Pair this server with a local nanobot. No public WebUI or relay.")


def _default_host() -> str:
    """Suggest this server's address from the SSH session or instance metadata.

    Outbound-IP lookup services can return a shared NAT/proxy, not this server.
    Only the recognized cloud's fixed public-address metadata field is queried.
    """
    fields = os.environ.get("SSH_CONNECTION", "").split()
    try:
        address = ipaddress.ip_address(fields[2]) if len(fields) == 4 else None
        if address and address.is_global and not address.is_multicast:
            return str(address)
    except ValueError:
        pass
    return _tencent_public_host()


def _tencent_public_host() -> str:
    """Read one non-secret field on Tencent instances; never probe other clouds.

    This is an operator-run setup command, not an agent HTTP tool. Keep metadata
    access fixed and local: no arbitrary URLs, redirects, proxies or credentials.
    A literal link-local endpoint avoids DNS/proxy delays on non-cloud networks.
    Unsupported installations and unavailable metadata keep the manual fallback.
    """
    try:
        if sys.platform != "linux" or Path("/sys/class/dmi/id/sys_vendor").read_text().strip() != "Tencent Cloud":
            return ""
    except (OSError, UnicodeError):
        return ""
    connection = http.client.HTTPConnection("169.254.0.23", timeout=1)
    try:
        connection.request("GET", "/latest/meta-data/public-ipv4",
                           headers={"Host": "metadata.tencentyun.com"})
        response = connection.getresponse()
        if response.status != 200:
            return ""
        raw = response.read(64)
        if len(raw) >= 64:
            return ""
        address = ipaddress.IPv4Address(raw.decode("ascii").strip())
        return str(address) if address.is_global and not address.is_multicast else ""
    except (OSError, ValueError, http.client.HTTPException):
        return ""
    finally:
        connection.close()


def _ssh_login_users() -> list[str]:
    """List regular interactive accounts, not root or service identities."""
    import pwd

    return sorted(u.pw_name for u in pwd.getpwall()
                  if 1000 <= u.pw_uid < 65534 and u.pw_shell.endswith(("/bash", "/sh", "/zsh")))


def _cloud_ssh_user() -> str | None:
    """Read only cloud-init's configured login name, never its full instance data."""
    cloud_init = shutil.which("cloud-init")
    if not cloud_init:
        return None
    try:
        result = subprocess.run([cloud_init, "query", "system_info.default_user.name"],
                                capture_output=True, text=True, timeout=2, check=False)
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _default_ssh_user() -> str | None:
    """Prefer the current login, then the cloud image's existing default account."""
    import pwd

    current = pwd.getpwuid(os.getuid())
    if current.pw_uid:
        return current.pw_name
    users = _ssh_login_users()
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user in users:
        return sudo_user
    if len(users) == 1:
        return users[0]
    if users:
        cloud_user = _cloud_ssh_user()
        if cloud_user in users:
            return cloud_user
    return None


def _choose_number(prompt: str, count: int) -> int:
    """Keep invalid selections in the current step, including across Typer versions."""
    while True:
        choice = int(typer.prompt(prompt, type=int))
        if 1 <= choice <= count:
            return choice
        typer.echo(f"Please choose a number from 1 to {count}.")


def _choose_ssh_user() -> str:
    """Ask only when discovery is ambiguous; never make the user invent a name."""
    user = _default_ssh_user()
    if user:
        return user
    users = _ssh_login_users()
    if not users:
        typer.echo("No regular login account was found on this server.\n"
                   "Ask the server administrator to set up a non-root login account, then try again.\n"
                   "No device was authorized and no server accounts were changed.")
        raise typer.Exit(1)
    typer.echo("\nThis server has several login accounts.\n"
               "Choose the one you normally use to log into this server, not your cloud website account.\n"
               "No password is needed here. If unsure, press Ctrl+C and ask the server administrator.")
    for index, name in enumerate(users, 1):
        typer.echo(f"  {index}. {name}")
    choice = _choose_number("Choose an account number", len(users))
    return users[choice - 1]


def _pair_as_administrator(request: str, config: Path, host: str, ssh_user: str, port: int) -> NoReturn:
    """Continue the same request only with the operator's explicit sudo consent."""
    typer.echo("\nnanobot's configuration is protected by another server account.")
    typer.echo(f"Config: {config}\nAdministrator access is needed to continue. File permissions will not change.")
    # Keep the installed environment (resolving a venv Python symlink loses it).
    # Isolated mode excludes CWD/PYTHONPATH; never forward the caller's environment
    # with sudo -E or re-evaluate a shell command supplied in the invitation.
    command = [str(Path(sys.executable).absolute()), "-I", "-m", "nanobot", "remote", "pair",
               request, "--config", str(config), "--port", str(port)]
    for option, value in (("--host", host or _default_host()),
                          ("--ssh-user", ssh_user or _default_ssh_user())):
        if value:
            command.extend([option, value])
    sudo = shutil.which("sudo")
    if os.getuid() == 0 or sudo is None:
        typer.echo("Ask the administrator to run this in nanobot's installation environment:")
        typer.echo(shlex.join(command))
        typer.echo("Do not make the config publicly readable.")
        raise typer.Exit(1)
    typer.echo("You may be asked for your server login password. You'll review device access next.")
    if not typer.confirm("Continue as server administrator?", default=False):
        typer.echo("Cancelled. No device was authorized. Run the pairing command again when ready.")
        raise typer.Exit(0)
    result = subprocess.run([sudo, "--", *command], check=False)
    if result.returncode:
        typer.echo("Pairing did not finish. Follow the message above, or ask your server administrator.\n"
                   "To retry, run the pairing command again; get a new command if it has expired.", err=True)
    raise typer.Exit(result.returncode if result.returncode >= 0 else 1)


@app.command()
def pair(
    request: str = typer.Argument(help="Public pairing request copied from your local WebUI"),
    host: str = typer.Option("", help="Public IP or hostname of this server, reachable from your computer"),
    ssh_user: str = typer.Option("", help="Existing non-root SSH login account"),
    port: int = typer.Option(22, min=1, max=65535, help="Existing SSH port; not changed"),
    config: Path | None = typer.Option(None, help="Existing nanobot config; discovered if omitted"),
) -> None:
    """Run in your server terminal, then open the returned link on your computer."""
    from nanobot.webui.remote_pairing import fingerprint, read_request, return_link
    from nanobot.webui.remote_ssh import RemoteError

    try:
        if sys.platform != "linux":
            raise RemoteError("pair_linux_required")
        from nanobot.webui.remote_pair_server import authorize, metadata

        invitation = read_request(request)
        host_key = " ".join(Path("/etc/ssh/ssh_host_ed25519_key.pub").read_text().split()[:2])
        if config is None:
            from nanobot.webui.remote_discovery import (
                _LOCATE,  # pyright: ignore[reportPrivateUsage]
                RemoteInspection,
            )

            result = subprocess.run([sys.executable, "-c", _LOCATE, str(get_home_path() / "config.json")], capture_output=True, text=True, timeout=8)
            records = [line.partition("NANOBOT_REMOTE:")[2] for line in result.stdout.splitlines() if "NANOBOT_REMOTE:" in line]
            candidates = RemoteInspection.model_validate_json(records[-1]).candidates if records else []
            if len(candidates) == 1:
                config = Path(candidates[0].config_path)
            elif candidates:
                for index, item in enumerate(candidates, 1):
                    typer.echo(f'{index}. {item.service or "nanobot"} — {item.config_path}')
                choice = _choose_number("Which nanobot?", len(candidates))
                config = Path(candidates[choice - 1].config_path)
            else:
                config = Path(typer.prompt("Path to your nanobot config"))
        config = config.expanduser().absolute()
        try:
            config = config.resolve()
            details = metadata(config)
        except (PermissionError, RemoteError) as exc:
            if not isinstance(exc, PermissionError) and str(exc) != "config_permission":
                raise
            _pair_as_administrator(request, config, host, ssh_user, port)
        if not ssh_user:
            ssh_user = _choose_ssh_user()
        if not host:
            host = _default_host()
            if not host:
                typer.echo("Could not detect this server's public address.\n"
                           "Use the public IP shown for this server in your cloud console, not your computer's IP.")
                host = typer.prompt("This server's public IP or hostname")
        typer.echo(f"\nAuthorize {invitation.label} to use nanobot on this server ({ssh_user}@{host})?\nConfig: {config}\nServer fingerprint: {fingerprint(host_key)}")
        typer.echo("This grants full nanobot WebUI access, including configured tools and settings.\nA dedicated SSH key can only reach this nanobot port; no shell or other forwarding.\nAuthorization lasts 90 days. No existing keys, firewall rules or model settings change.")
        if not typer.confirm("Authorize this computer?", default=False):
            typer.echo("Cancelled. No device was authorized. Run the pairing command again when ready.")
            return
        # Check the service is running before granting access; no credential is sent.
        import socket

        with socket.create_connection(("127.0.0.1", details["port"]), timeout=5):
            pass
        code = authorize(invitation, host=host, user=ssh_user, ssh_port=port, config=config,
                         host_key=host_key, until=int(time.time()) + 90 * 86400)
        link = return_link(invitation, code)
        if link:
            typer.echo("\nReturn to nanobot on your computer to finish connecting:")
            typer.echo("Open this link in the same computer/browser that started pairing.\n")
            typer.echo(link)
            typer.echo("\nIf your terminal cannot open links, paste this connection code into nanobot:\n")
        else:
            typer.echo("\nPaste this connection code into the same local nanobot window:\n")
        typer.echo(code)
        typer.echo(f"\nTo revoke new connections: nanobot remote revoke {invitation.id} --ssh-user {ssh_user}")
        typer.echo("Close any already-open remote sessions as well. Re-pair after changing the WebUI secret or port.")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, RemoteError) as exc:
        typer.echo(f"Pairing not completed: {str(exc) if isinstance(exc, RemoteError) else 'check server config, login account and SSH installation'}. Existing settings were not reset.", err=True)
        if str(exc) == "config_permission":
            typer.echo("The nanobot config belongs to another account. Run this command in its installation environment as the server administrator, or ask that administrator to pair it. Do not make the config publicly readable.", err=True)
        raise typer.Exit(1) from None


@app.command()
def revoke(device: str, ssh_user: str = typer.Option("", help="SSH account used when pairing")) -> None:
    """Remove only this device's managed SSH authorization, preserving other keys."""
    import getpass

    from nanobot.webui.remote_ssh import RemoteError

    try:
        if sys.platform != "linux":
            raise RemoteError("pair_linux_required")
        from nanobot.webui.remote_pair_server import as_account

        user = ssh_user or getpass.getuser()
        typer.confirm(f"Revoke device {device} for SSH account {user}?", abort=True, default=False)
        as_account(user, "revoke", {"id": device})
        typer.echo("Authorization removed. Already-open SSH sessions must also be closed.")
    except (OSError, KeyError, RemoteError, subprocess.SubprocessError):
        typer.echo("Could not revoke. Check the device ID and run as the SSH account or server administrator.", err=True)
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
