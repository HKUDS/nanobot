"""SSH-only access to an existing nanobot. Never installs or starts a remote process.

The system SSH client owns key/agent authentication and host verification. Probe
output is private: only the WebUI credential is read, never provider credentials.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import shlex
import shutil
import socket
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nanobot.webui.remote_mux import SSHMaster

_BRIDGE_READY = b"NANOBOT_REMOTE_BRIDGE_2\n"


class RemoteError(Exception):
    """A stable, non-secret error code for the connection UI."""


class RemoteProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=64)
    host: str = Field(min_length=1, max_length=253, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:@-]*$")
    port: int | None = Field(default=None, ge=1, le=65535)
    ssh_config: str = Field(default="", max_length=2048)
    identity_file: str = Field(default="", max_length=2048)
    config_path: str = Field(default="~/.nanobot/config.json", min_length=1, max_length=2048)
    runtime_user: str = Field(default="", max_length=64, pattern=r"^([a-zA-Z_][a-zA-Z0-9_-]*)?$")

    @field_validator("ssh_config", "identity_file", "config_path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError("control characters are not allowed")
        return value


class PairedSSHProfile(RemoteProfile):
    """Internal transport marker. Not accepted by the editable profile API."""


def transport_arguments(profile: RemoteProfile, remote_port: int, known_hosts: Path | None) -> list[str]:
    args = ssh_arguments(profile, known_hosts)
    if isinstance(profile, PairedSSHProfile):
        # The server key's forced command owns the fixed destination. Do not
        # request forwarding or execute the ordinary credential probe.
        return [*args, profile.host, "nanobot-remote-bridge-v2"]
    return [*args, "-W", f"127.0.0.1:{remote_port}", profile.host]


# Frame the result so login banners don't get mistaken for invalid config JSON.
_PROBE_PREFIX = b"\x1eNANOBOT_REMOTE:"

# Fixed program, quoted as one shell argument. No user-supplied shell commands.
_PROBE = r'''
import json, os, pathlib, socket, sys
def emit(value):
    print("\n\x1eNANOBOT_REMOTE:" + json.dumps(value))
try:
    path = pathlib.Path(sys.argv[1]).expanduser()
    data = json.loads(path.read_text())
    ws = data.get("channels", {}).get("websocket", {})
    secret = ws.get("tokenIssueSecret") or ws.get("token_issue_secret") or ws.get("token")
    if not ws.get("enabled"):
        raise ValueError("webui_disabled")
    if not isinstance(secret, str) or not secret.strip() or "${" in secret:
        raise ValueError("webui_auth_required")
    if ws.get("publicWsUrl") or ws.get("public_ws_url"):
        raise ValueError("public_ws_unsupported")
    if ws.get("trustedProxyAuth") or ws.get("trusted_proxy_auth"):
        raise ValueError("incompatible_gateway")
    emit({"port": ws.get("port", 8765), "secret": secret,
                      "token_issue_path": ws.get("tokenIssuePath") or ws.get("token_issue_path") or "",
                      "hostname": socket.gethostname(), "config_path": str(path)})
except FileNotFoundError:
    emit({"error": "config_not_found"})
except PermissionError:
    emit({"error": "config_permission"})
except ValueError as e:
    code = str(e)
    emit({"error": code if code in {"webui_disabled", "webui_auth_required", "public_ws_unsupported", "incompatible_gateway"} else "config_invalid"})
except (AttributeError, TypeError):
    emit({"error": "config_invalid"})
'''


def ssh_arguments(profile: RemoteProfile, known_hosts: Path | None = None) -> list[str]:
    executable = shutil.which("ssh")
    if not executable:
        raise RemoteError("ssh_unavailable")
    args = [executable]
    if isinstance(profile, PairedSSHProfile) and not profile.ssh_config:
        args.extend(["-F", os.devnull])
    for flag, value in [("-F", profile.ssh_config), ("-i", profile.identity_file)]:
        if value:
            path = Path(value).expanduser()
            if not path.is_file():
                raise RemoteError("local_file_not_found")
            args.extend([flag, str(path)])
    # CLI options override config. Never forward the agent or reuse an unrelated
    # multiplexed session (whose identity/forwarding policy could be different).
    args.extend([
        "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", "ForwardAgent=no", "-o", "ForwardX11=no", "-o", "PermitLocalCommand=no",
        "-o", "ControlMaster=no", "-o", "ControlPath=none", "-o", "ConnectTimeout=10",
        "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2",
        "-o", "ExitOnForwardFailure=yes", "-o", "RequestTTY=no",
        # Interactive aliases may start tmux or another shell automatically.
        # This connection runs only our fixed probe and forwarding transport.
        # Older clients lack these settings and the corresponding behavior.
        "-o", "IgnoreUnknown=StdinNull,ForkAfterAuthentication,RemoteCommand",
        "-o", "RemoteCommand=none",
        "-o", "ClearAllForwardings=yes", "-o", "StdinNull=no",
        "-o", "ForkAfterAuthentication=no",
    ])
    if profile.port is not None:
        args.extend(["-p", str(profile.port)])
    if isinstance(profile, PairedSSHProfile):
        # Never fall back to a user's unrelated identity or agent for this grant.
        args.extend(["-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none"])
    if known_hosts and known_hosts.is_file():
        args.extend(["-o", f"UserKnownHostsFile={known_hosts}", "-o", "GlobalKnownHostsFile=none",
                     "-o", "HostKeyAlias=nanobot-remote", "-o", "HostKeyAlgorithms=ssh-ed25519",
                     "-o", "UpdateHostKeys=no"])
    return args


def ssh_error(stderr: bytes) -> str:
    text = stderr.decode("utf-8", errors="replace").lower()
    if "host identification has changed" in text:
        return "host_key_changed"
    if "host key verification failed" in text or "no ed25519 host key is known" in text:
        return "host_key_unknown"
    if "sudo:" in text:
        return "runtime_user_denied"
    if "unprotected private key file" in text or "bad permissions" in text:
        return "ssh_key_permissions"
    if "agent refused operation" in text or "signing failed" in text:
        return "ssh_agent_refused"
    if "bad configuration option" in text or "terminating, 1 bad configuration" in text:
        return "ssh_config_invalid"
    if "administratively prohibited" in text:
        return "ssh_forwarding_denied"
    if "open failed: connect failed" in text:
        return "remote_unreachable"
    if "too many authentication failures" in text:
        return "ssh_too_many_keys"
    if "permission denied" in text:
        return "ssh_auth_failed"
    if "connection refused" in text:
        return "ssh_refused"
    if "could not resolve hostname" in text:
        return "ssh_host_not_found"
    if "connection closed" in text or "connection reset" in text:
        return "ssh_connection_closed"
    if "python3" in text and "not found" in text:
        return "python_unavailable"
    return "ssh_unreachable"


async def stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), 3)
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()


async def run_check(
    profile: RemoteProfile, program: str, known_hosts: Path | None = None,
) -> dict[str, Any]:
    """Run a fixed read-only program with SSH's existing identity and trust policy."""
    remote = ["python3", "-c", program, profile.config_path]
    if profile.runtime_user:
        remote = ["sudo", "-n", "-H", "-u", profile.runtime_user, "--", *remote]
    process = await asyncio.create_subprocess_exec(
        *ssh_arguments(profile, known_hosts), profile.host, shlex.join(remote),
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 20)
        if process.returncode:
            raise RemoteError(ssh_error(stderr))
        try:
            records = [line[len(_PROBE_PREFIX):] for line in stdout.split(b"\n")
                       if line.startswith(_PROBE_PREFIX)]
            if len(records) != 1:
                raise ValueError
            raw = json.loads(records[0])
            if not isinstance(raw, dict):
                raise ValueError
            data = cast(dict[str, Any], raw)
            if data.get("error"):
                raise RemoteError(str(data["error"]))
            return data
        except (ValueError, TypeError):
            raise RemoteError("probe_failed") from None
    except TimeoutError:
        raise RemoteError("ssh_unreachable") from None
    finally:
        await stop_process(process)


async def probe(profile: RemoteProfile, known_hosts: Path | None = None) -> dict[str, Any]:
    data = await run_check(profile, _PROBE, known_hosts)
    if (not isinstance(data.get("secret"), str) or not data["secret"]
            or type(data.get("port")) is not int or not 1 <= data["port"] <= 65535):
        raise RemoteError("probe_failed")
    return data


async def pairing_route(source: RemoteProfile, target_host: str) -> str:
    """Explicitly reuse a saved route, never its identities or target settings."""
    process = await asyncio.create_subprocess_exec(
        *ssh_arguments(source), "-G", source.host,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        stdin=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 10)
        if process.returncode:
            raise RemoteError("ssh_config_invalid")
        values = dict(line.split(" ", 1) for line in output.decode().splitlines() if " " in line)
        if values.get("hostname", "").lower() != target_host.lower():
            raise RemoteError("pair_route_mismatch")
        if values.get("proxyjump", "none") != "none":
            raise RemoteError("pair_route_unsupported")
        lines = ["Host *"]
        for option in ("proxycommand", "bindaddress", "bindinterface"):
            value = values.get(option, "none")
            if value != "none":
                lines.append(f"    {option} {value}")
        return "\n".join(lines) + "\n"
    except TimeoutError:
        raise RemoteError("ssh_unreachable") from None
    finally:
        await stop_process(process)


class Tunnel:
    """Own a private loopback transport; upstream bytes only use SSH pipes.

    Pausing closes streams, not the listener: other browser tabs may still retry
    that origin. Only final owner shutdown relinquishes the listening socket.
    """

    def __init__(self, args: list[str], port: int) -> None:
        self.args = args
        self.port = port
        self.server: asyncio.Server | None = None
        self.enabled = True
        self.error = ""
        self._streams: set[asyncio.Task[None]] = set()
        self._master: SSHMaster | None = None
        self._master_args: tuple[list[str], str] | None = None
        self._paired = False
        self._reuse_verified = False
        self._probe_started = False
        # Leave room below OpenSSH's usual MaxSessions=10, including a live WS.
        self._slots = asyncio.Semaphore(8)

    @property
    def active(self) -> bool:
        return self.enabled and self.server is not None and self.server.is_serving()

    def resume(self, profile: RemoteProfile, remote_port: int, known_hosts: Path | None) -> None:
        self.args = transport_arguments(profile, remote_port, known_hosts)
        self._paired = isinstance(profile, PairedSSHProfile)
        self._master_args = ((ssh_arguments(profile, known_hosts), profile.host)
                             if os.name != "nt" and known_hosts and known_hosts.is_file() else None)
        self._master = SSHMaster(*self._master_args) if self._master_args else None
        self._reuse_verified = not self._paired
        self._probe_started = False
        self.error = ""
        self.enabled = True

    def accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if not self.active or len(self._streams) >= 32:
            writer.close()
            return
        task = asyncio.create_task(self._relay(reader, writer))
        self._streams.add(task)

        def finished(task: asyncio.Task[None]) -> None:
            self._streams.discard(task)
            # Cancellation can happen before _relay enters its try/finally.
            writer.close()

        task.add_done_callback(finished)

    async def _relay(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async with self._slots:
            await self._stream(reader, writer)

    async def _stream(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        process: asyncio.subprocess.Process | None = None
        pumps: list[asyncio.Task[None]] = []
        stderr = bytearray()
        master: SSHMaster | None = None

        async def copy(source: asyncio.StreamReader, destination: asyncio.StreamWriter) -> None:
            while data := await source.read(65536):
                destination.write(data)
                await destination.drain()
            if destination.can_write_eof():
                destination.write_eof()

        async def drain_errors(source: asyncio.StreamReader) -> None:
            while data := await source.read(4096):
                stderr.extend(data[:max(0, 8192 - len(stderr))])

        try:
            if self._master and (self._reuse_verified or not self._probe_started):
                # The first channel follows fresh SSH authentication. Only a
                # guarded bridge can authorize MORE channels on that transport.
                master = self._master
                self._probe_started = True
            args = await master.arguments(self.args) if master else self.args
            # Shield process creation so cancellation cannot lose a spawned child
            # before we have its handle and can reap it.
            spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                *args, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            ))
            try:
                process = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                process = await spawn
                raise
            assert process is not None
            assert process.stdin is not None and process.stdout is not None and process.stderr is not None
            async def response() -> None:
                assert process is not None and process.stdout is not None
                if self._paired:
                    first = await process.stdout.readline()
                    if first == _BRIDGE_READY:
                        # Only the guarded bridge advertises this capability.
                        # Old bridges forward HTTP unchanged: keep authenticating
                        # every stream until the server bridge is upgraded.
                        self._reuse_verified = True
                        if self._master_args and self._master is None:
                            self._master = SSHMaster(*self._master_args)
                    else:
                        self._reuse_verified = False
                        writer.write(first)
                        await writer.drain()
                await copy(process.stdout, writer)

            pumps = [asyncio.create_task(copy(reader, process.stdin)),
                     asyncio.create_task(response()),
                     asyncio.create_task(drain_errors(process.stderr))]
            done, _ = await asyncio.wait(pumps[:2], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                await task
            # Preserve a client's half-close while draining the final response.
            # Conversely, EOF from SSH must wake an idle keepalive client.
            await pumps[1]
            pumps[0].cancel()
            process.stdin.close()
            await asyncio.wait_for(process.wait(), 3)
            await pumps[2]
            if process.returncode:
                self.error = ssh_error(bytes(stderr))
        except RemoteError as exc:
            self.error = str(exc)
        except (OSError, ConnectionError, ValueError):
            self.error = "ssh_unreachable"
        finally:
            for task in pumps:
                task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            if process is not None:
                await stop_process(process)
            if master is not None and not self._reuse_verified:
                await master.close()
                if self._master is master:
                    self._master = None
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def pause(self) -> None:
        self.enabled = False
        streams = list(self._streams)
        for task in streams:
            task.cancel()
        await asyncio.gather(*streams, return_exceptions=True)
        if self._master is not None:
            await self._master.close()
            self._master = None

    async def close(self) -> None:
        await self.pause()
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()


def _listen(local_port: int, excluded_ports: set[int]) -> socket.socket:
    # Never release the chosen socket between validation and use. Windows reuse
    # has different semantics; exclusive binding rejects existing listeners.
    rejected: list[socket.socket] = []
    try:
        for _ in range(128):
            listener = socket.socket()
            try:
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                else:
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", local_port))
                listener.listen()
                if not local_port and listener.getsockname()[1] in excluded_ports:
                    rejected.append(listener)
                    continue
                listener.setblocking(False)
                return listener
            except BaseException:
                listener.close()
                raise
        raise RemoteError("local_port_in_use")
    except OSError:
        raise RemoteError("local_port_in_use") from None
    finally:
        for listener in rejected:
            listener.close()


async def open_tunnel(
    profile: RemoteProfile, remote_port: int, known_hosts: Path | None = None,
    local_port: int = 0,
    *, excluded_ports: set[int] | None = None,
) -> Tunnel:
    args = transport_arguments(profile, remote_port, known_hosts)
    listener = _listen(local_port, excluded_ports or set())
    tunnel = Tunnel(args, int(listener.getsockname()[1]))
    try:
        tunnel.resume(profile, remote_port, known_hosts)
        tunnel.server = await asyncio.start_server(tunnel.accept, sock=listener)
        return tunnel
    except BaseException:
        listener.close()
        await tunnel.close()
        raise


async def scan_host_key(profile: RemoteProfile) -> tuple[str, str]:
    """Return an UNVERIFIED key and fingerprint, never silently trust it.

    Resolve SSH aliases with the user's own config. Scanning is deliberately
    direct; jump-host-only setups should verify via their existing SSH config.
    """
    keyscan = shutil.which("ssh-keyscan")
    if not keyscan:
        raise RemoteError("ssh_unavailable")
    process = await asyncio.create_subprocess_exec(
        *ssh_arguments(profile), "-G", profile.host,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 10)
        if process.returncode:
            raise RemoteError("ssh_unreachable")
    finally:
        await stop_process(process)
    settings = dict(line.split(" ", 1) for line in output.decode().splitlines() if " " in line)
    hostname, port = settings.get("hostname", ""), settings.get("port", "22")
    if not hostname or hostname.startswith("-") or not port.isdigit():
        raise RemoteError("invalid_profile")
    scan = await asyncio.create_subprocess_exec(
        keyscan, "-T", "5", "-p", port, "-t", "ed25519", hostname,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(scan.communicate(), 8)
        for line in output.decode().splitlines():
            fields = line.split()
            if len(fields) != 3 or fields[1] != "ssh-ed25519":
                continue
            try:
                binary = base64.b64decode(fields[2], validate=True)
            except ValueError:
                continue
            fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(binary).digest()).decode().rstrip("=")
            return f"nanobot-remote ssh-ed25519 {fields[2]}\n", fingerprint
        raise RemoteError("host_key_scan_failed")
    except TimeoutError:
        raise RemoteError("host_key_scan_failed") from None
    finally:
        await stop_process(scan)
