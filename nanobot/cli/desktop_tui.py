"""Strict Desktop client entrypoint and pipe-only, current-user credential resolver.

Unlike the normal TUI launcher, this module never loads a Config or acquires a
gateway lease. The resolver is also executable with ``python -I -S <this file>``.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

if __name__ == "__main__":
    # Only the package beside this trusted script, not cwd/user-site/PYTHONPATH.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nanobot.cli.desktop_target import (
    DesktopTarget,
    DesktopTargetError,
    discover_desktop_target,
)

PROTOCOL_VERSION = 1
_MAX_BYTES = 8192


def _connection(target: DesktopTarget, gateway_id: str | None = None) -> dict[str, object]:
    reply = target.request("tui")
    value = reply.tui
    if reply.state != "ready" or "tui" not in reply.capabilities or value is None:
        raise DesktopTargetError("Desktop does not support terminal attachment")
    identity = value.get("gatewayId")
    if type(value.get("protocolVersion")) is not int or value["protocolVersion"] != 1:
        raise DesktopTargetError("Unsupported terminal protocol")
    if not isinstance(identity, str) or (gateway_id is not None and identity != gateway_id):
        raise DesktopTargetError("Desktop gateway identity changed")
    try:
        uuid.UUID(identity)
    except ValueError as exc:
        raise DesktopTargetError("Invalid gateway identity") from exc
    api = _endpoint(value.get("apiUrl"), websocket=False)
    ws = _endpoint(value.get("wsUrl"), websocket=True)
    if (api.hostname, api.port or 80) != (ws.hostname, ws.port or 80) or api.path not in {"", "/"}:
        raise DesktopTargetError("Terminal endpoints must share the same loopback listener")
    for key in ("wsToken", "apiToken"):
        token = value.get(key)
        if not isinstance(token, str) or not 1 <= len(token) <= 2048 or any(
            ord(char) < 33 or ord(char) > 126 for char in token
        ):
            raise DesktopTargetError("Invalid terminal credentials")
    # Do not forward unknown fields or untrusted executable/config paths.
    return {key: value[key] for key in (
        "protocolVersion", "gatewayId", "apiUrl", "wsUrl", "wsToken", "apiToken",
    )}


def _endpoint(value: object, *, websocket: bool):
    if not isinstance(value, str) or "\\" in value or any(
        ord(char) < 33 or ord(char) == 127 for char in value
    ):
        raise DesktopTargetError("Invalid terminal endpoint")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise DesktopTargetError("Invalid terminal endpoint") from exc
    if (
        parsed.scheme != ("ws" if websocket else "http")
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or port == 0
        or parsed.username is not None or parsed.password is not None
        or parsed.query or parsed.fragment
    ):
        raise DesktopTargetError("Terminal endpoint is not a literal loopback address")
    return parsed


def resolve_request(raw: bytes) -> dict[str, object]:
    """Re-discover the selected Desktop; never substitute a newly started instance."""
    if len(raw) > _MAX_BYTES:
        raise DesktopTargetError("Invalid resolver request")
    value: object = json.loads(raw)
    if not isinstance(value, dict):
        raise DesktopTargetError("Invalid resolver request")
    fields = cast(dict[str, object], value)
    identity, gateway_id = fields.get("instanceId"), fields.get("gatewayId")
    if not isinstance(identity, str) or not isinstance(gateway_id, str):
        raise DesktopTargetError("Invalid resolver identity")
    target = discover_desktop_target()
    if target is None or target.instance_id != identity:
        raise DesktopTargetError("Selected Desktop disconnected")
    return _connection(target, gateway_id)


def launch_desktop_tui(target: DesktopTarget) -> int:
    from nanobot.cli.tui_launcher import TuiUnavailableError, resolve_tui_command

    process: subprocess.Popen[bytes] | None = None
    try:
        current = _connection(target)
        # Resolve/install only the matching terminal client, never a backend.
        cache = os.environ.get("NANOBOT_DESKTOP_CLIENT_CACHE")
        if cache is not None and not Path(cache).is_absolute():
            raise DesktopTargetError("Desktop client cache must be absolute")
        command = resolve_tui_command(data_dir=Path(cache)) if cache else resolve_tui_command()
        # An old client may ignore the probe flag. It must not consume terminal
        # input or connect using credentials inherited from another TUI session.
        env = {key: value for key, value in os.environ.items() if not key.startswith("NANOBOT_TUI_")}
        probe = subprocess.run(
            [*command, "--desktop-protocol"], capture_output=True, timeout=15, check=False,
            stdin=subprocess.DEVNULL, env=env,
        )
        if probe.returncode != 0 or probe.stdout.strip() != b"1":
            raise DesktopTargetError("The terminal client does not support Desktop attachment")
        env["NANOBOT_TUI_DESKTOP_RESOLVER"] = json.dumps([
            sys.executable, "-I", "-S", str(Path(__file__).resolve()), "--resolve",
        ])
        env["NANOBOT_TUI_DESKTOP_TARGET"] = json.dumps({
            "instanceId": target.instance_id, "gatewayId": current["gatewayId"],
        })
        process = subprocess.Popen(command, env=env)
        code = process.wait()
        return 0 if code == 90 else code
    except (OSError, ValueError, subprocess.SubprocessError, TuiUnavailableError) as exc:
        raise DesktopTargetError("Desktop terminal attachment failed") from exc
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main() -> None:
    args = sys.argv[1:]
    if args == ["--resolve"]:
        try:
            # Secret output is permitted only through a pipe captured by our TUI.
            if not _anonymous_output(sys.stdout.fileno()):
                raise DesktopTargetError("Resolver requires a pipe")
            raw = sys.stdin.buffer.readline(_MAX_BYTES + 1)
            if not raw.endswith(b"\n"):
                raise DesktopTargetError("Incomplete resolver request")
            payload = json.dumps(resolve_request(raw), separators=(",", ":")).encode()
            if len(payload) > _MAX_BYTES:
                raise DesktopTargetError("Resolver response is too large")
            sys.stdout.buffer.write(payload + b"\n")
            return
        except Exception:
            raise SystemExit(3) from None  # Never print credential-bearing exceptions.
    if args == ["--protocol"]:
        print(PROTOCOL_VERSION)
        return
    if args or os.environ.get("_NANOBOT_COMPLETE") or not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SystemExit(2)
    try:
        target = discover_desktop_target()
        if target is None:
            raise DesktopTargetError("Desktop is absent")
        expected = os.environ.get("NANOBOT_DESKTOP_EXPECTED_INSTANCE")
        if expected is not None and target.instance_id != expected:
            raise DesktopTargetError("Selected Desktop changed")
        raise SystemExit(launch_desktop_tui(target))
    except DesktopTargetError:
        print("Desktop terminal connection unavailable. Start or update Desktop; no backend was started.", file=sys.stderr)
        raise SystemExit(3) from None


def _anonymous_output(fd: int) -> bool:
    """Bun uses an unnamed Unix socket pair for its captured subprocess stdout."""
    mode = os.fstat(fd).st_mode
    if stat.S_ISFIFO(mode):
        return True
    if os.name == "posix" and stat.S_ISSOCK(mode):
        with socket.fromfd(fd, socket.AF_UNIX, socket.SOCK_STREAM) as stream:
            return stream.getsockname() == "" and stream.getpeername() == ""
    return False


if __name__ == "__main__":
    main()
