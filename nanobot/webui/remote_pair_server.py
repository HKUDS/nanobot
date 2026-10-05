"""Explicit server-side authorization for relay-free remote WebUI pairing.

Only an already-authorized server operator runs this module. No daemon, sudoers
rule, listener or SSH policy is installed. The dedicated key executes one fixed
stdio bridge, with all OpenSSH forwarding and interactive features disabled.
"""

from __future__ import annotations

import datetime
import json
import os
import shlex
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from nanobot.webui.remote_pairing import PairReceipt, PairRequest, private_write, public_key, seal
from nanobot.webui.remote_ssh import RemoteError

# No dynamic command, destination or environment input is accepted by the bridge.
# SSH_ORIGINAL_COMMAND only negotiates the guard marker, never executed.
# Each invocation is one TCP stream to the fixed loopback destination.
_BRIDGE = '''import os, socket, threading, pathlib, sys, time
# A multiplexed SSH transport authenticates only once. Re-check the exact
# managed grant on EVERY new channel, including expiry and operator revocation.
root = pathlib.Path(__file__).resolve().parent
try:
    line = (root / "authorization").read_text()
    keys = root.parents[1] / "authorized_keys"
    valid = line.endswith(" nanobot-remote:" + root.name + "\\n") and line in keys.read_text().splitlines(keepends=True)
except (OSError, ValueError):
    valid = False
if not valid or time.time() >= UNTIL:
    sys.stderr.write("Permission denied: device authorization expired or revoked\\n")
    sys.exit(1)
if os.environ.get("SSH_ORIGINAL_COMMAND") == "nanobot-remote-bridge-v2":
    os.write(1, b"NANOBOT_REMOTE_BRIDGE_2\\n")
s = socket.create_connection(("127.0.0.1", PORT), timeout=10)
s.settimeout(None)
def send():
    try:
        while True:
            data = os.read(0, 65536)
            if not data:
                break
            s.sendall(data)
        s.shutdown(socket.SHUT_WR)
    except OSError:
        s.close()
threading.Thread(target=send, daemon=True).start()
try:
    while True:
        data = s.recv(65536)
        if not data:
            break
        while data:
            data = data[os.write(1, data):]
finally:
    s.close()
'''


def bridge_source(port: int, until: int) -> str:
    """Render only fixed, operator-approved destination and authorization expiry."""
    return _BRIDGE.replace("PORT", str(port)).replace("UNTIL", str(until))


def metadata(config: Path) -> dict[str, Any]:
    """Read only the WebUI credential out of the operator-selected config."""
    try:
        raw = json.loads(config.read_text())
        ws = raw.get("channels", {}).get("websocket", {})
        secret = ws.get("tokenIssueSecret") or ws.get("token_issue_secret") or ws.get("token")
        if not ws.get("enabled") or not isinstance(secret, str) or not secret.strip() or "${" in secret:
            raise RemoteError("webui_auth_required")
        if ws.get("publicWsUrl") or ws.get("public_ws_url") or ws.get("trustedProxyAuth") or ws.get("trusted_proxy_auth"):
            raise RemoteError("incompatible_gateway")
        port = ws.get("port", 8765)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError
        return {"port": port, "secret": secret, "hostname": socket.gethostname(),
                "config_path": str(config.resolve()),
                "token_issue_path": ws.get("tokenIssuePath") or ws.get("token_issue_path") or ""}
    except PermissionError:
        raise RemoteError("config_permission") from None
    except (OSError, ValueError, TypeError, AttributeError):
        raise RemoteError("config_invalid") from None


def _directory(path: Path) -> None:
    if path.is_symlink():
        raise RemoteError("pair_ssh_layout")
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise RemoteError("pair_ssh_layout")


def write_authorization(home: Path, request: PairRequest, port: int, until: int) -> None:
    """Runs as the SSH account, never with root privileges over another home."""
    import fcntl

    request.check_expiry()
    ssh = home / ".ssh"
    _directory(ssh)
    root = ssh / "nanobot-remote"
    _directory(root)
    target = root / request.id
    # Only our lock file; do not change permissions/content of unrelated keys.
    lock = os.open(root / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock, "r+") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        if target.exists():
            raise RemoteError("pair_used")
        target.mkdir(mode=0o700)
        try:
            bridge = target / "bridge.py"
            private_write(bridge, bridge_source(port, until).encode())
            command = shlex.join(["/usr/bin/python3", "-I", "-S", str(bridge)]).replace("\\", "\\\\").replace('"', '\\"')
            expiry = datetime.datetime.fromtimestamp(until, datetime.UTC).strftime("%Y%m%d%H%M%SZ")
            line = f'restrict,expiry-time="{expiry}",command="{command}" {request.ssh_key} nanobot-remote:{request.id}\n'
            private_write(target / "authorization", line.encode())
            _update_keys(ssh / "authorized_keys", add=line)
        except BaseException:
            # Never remove an existing directory or unrelated key on rollback.
            for name in ("bridge.py", "authorization"):
                (target / name).unlink(missing_ok=True)
            target.rmdir()
            raise


def _update_keys(path: Path, *, add: str = "", remove: str = "") -> None:
    import fcntl

    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise RemoteError("pair_ssh_layout")
        # Existing authorized_keys files are often created with a default umask of
        # 0644. Normalize them to the SSH-safe owner-only mode before mutating the
        # file, while preserving the original user-owned layout and contents.
        os.fchmod(handle.fileno(), 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        original = handle.read(1024 * 1024 + 1)
        if len(original) > 1024 * 1024:
            raise RemoteError("pair_ssh_layout")
        if add:
            handle.seek(0, 2)
            handle.write(("\n" if original and not original.endswith("\n") else "") + add)
        else:
            # Exact managed line, not a substring/comment match.
            replacement = "".join(line for line in original.splitlines(keepends=True) if line != remove)
            if replacement == original:
                return
            temporary_fd, temporary_name = tempfile.mkstemp(prefix=".nanobot-revoke-", dir=path.parent)
            try:
                with os.fdopen(temporary_fd, "w") as output:
                    output.write(replacement)
                    output.flush()
                    os.fsync(output.fileno())
                    os.fchmod(output.fileno(), 0o600)
                os.replace(temporary_name, path)
            finally:
                Path(temporary_name).unlink(missing_ok=True)
        handle.flush()
        os.fsync(handle.fileno())


def remove_authorization(home: Path, key: str) -> None:
    import fcntl

    from nanobot.webui.remote_pairing import PairStore

    # Validate before joining any path, even for a manually typed revoke command.
    PairStore(home).path(key)
    root = home / ".ssh" / "nanobot-remote"
    _directory(home / ".ssh")
    _directory(root)
    target = root / key
    if target.is_symlink() or not target.is_dir():
        raise RemoteError("pair_invalid")
    lock = os.open(root / "lock", os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(lock, "r+") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        line = (target / "authorization").read_text()
        if not line.endswith(f" nanobot-remote:{key}\n") or "\n" in line[:-1]:
            raise RemoteError("pair_invalid")
        _update_keys(home / ".ssh/authorized_keys", remove=line)
        # Keep the non-secret receipt/bridge for an auditable, retryable revoke.


def as_account(user: str, operation: str, data: dict[str, Any]) -> None:
    import pwd

    account = pwd.getpwnam(user)
    if account.pw_uid == 0 or account.pw_shell.endswith(("/nologin", "/false")):
        raise RemoteError("pair_login_user")
    if os.getuid() not in (0, account.pw_uid):
        raise RemoteError("config_permission")
    child = dict(data, home=account.pw_dir, operation=operation)
    # Drop all supplementary groups *before* any write in a user-owned home.
    options: dict[str, Any] = {}
    if os.getuid() == 0:
        options = {"user": account.pw_uid, "group": account.pw_gid, "extra_groups": []}
    result = subprocess.run(
        [sys.executable, "-m", "nanobot.webui.remote_pair_server"],
        input=json.dumps(child), text=True, capture_output=True, timeout=20, **options,
    )
    if result.returncode:
        code = result.stdout.strip()
        raise RemoteError(code if code in {"pair_used", "pair_expired", "pair_ssh_layout", "pair_invalid"} else "pair_install_failed")


def authorize(request: PairRequest, *, host: str, user: str, ssh_port: int,
              config: Path, host_key: str, until: int) -> str:
    request.check_expiry()
    receipt = PairReceipt(id=request.id, ssh_key=request.ssh_key, host=host, user=user,
                          ssh_port=ssh_port, host_key=public_key(host_key), authorized_until=until,
                          **metadata(config))
    encrypted = seal(request, receipt)  # Fail crypto/validation before authorizing anything.
    as_account(user, "install", {"request": request.model_dump(), "port": receipt.port, "until": until})
    return encrypted


if __name__ == "__main__":
    try:
        data = json.loads(sys.stdin.read(32768))
        if data["operation"] == "install":
            write_authorization(Path(data["home"]), PairRequest.model_validate(data["request"]), data["port"], data["until"])
        elif data["operation"] == "revoke":
            remove_authorization(Path(data["home"]), data["id"])
        else:
            raise RemoteError("pair_invalid")
    except Exception as exc:
        print(str(exc) if isinstance(exc, RemoteError) else "pair_install_failed")
        sys.exit(1)
