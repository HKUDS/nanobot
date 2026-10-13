"""Copy/paste pairing protocol. Private material never enters the WebUI response.

The request is public. A receipt is encrypted for the requesting local instance;
its provenance is the user's trusted server terminal, not a public relay. SSH's
host key is pinned from that receipt before any credential-bearing connection.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import socket
import time
import uuid
from pathlib import Path
from typing import Any, cast

from cryptography.exceptions import InvalidTag, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from nanobot.webui.remote_ssh import RemoteError, RemoteProfile

_TTL = 600
_CONTEXT = b"nanobot-remote-pair-v1"


def local_return_origin(value: str) -> str:
    """Only the local top-level WebUI can receive a pairing link. No redirects."""
    if value == "":
        return value
    match = re.fullmatch(r"http://(127\.0\.0\.1|localhost|\[::1\])(?::([0-9]{1,5}))?", value)
    if not match or (match[2] is not None and not 1 <= int(match[2]) <= 65535):
        raise ValueError("local return address required")
    return value


def return_link(request: PairRequest, code: str) -> str:
    # Fragment data is never sent in the HTTP request or Referer. The frontend
    # scrubs it before authentication and still requires a confirmation.
    if not request.return_origin:
        return ""
    if not re.fullmatch(r"nbpc1\.[A-Za-z0-9_-]{1,32762}", code):
        raise RemoteError("pair_invalid")
    return f"{local_return_origin(request.return_origin)}/#/remote?pairing={code}"


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def decode(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def pack(prefix: str, data: dict[str, Any]) -> str:
    return prefix + encode(json.dumps(data, separators=(",", ":")).encode())


def unpack(prefix: str, value: str) -> dict[str, Any]:
    if len(value) > 32768:
        raise RemoteError("pair_invalid")
    value = "".join(value.split())
    try:
        if not value.startswith(prefix):
            raise ValueError
        raw = json.loads(decode(value[len(prefix):]))
        if not isinstance(raw, dict):
            raise ValueError
        return cast(dict[str, Any], raw)
    except (ValueError, TypeError, UnicodeError):
        raise RemoteError("pair_invalid") from None


def public_key(value: str) -> str:
    """Accept exactly one Ed25519 key, without options, comments or newlines."""
    try:
        key = serialization.load_ssh_public_key(value.encode())
    except UnsupportedAlgorithm:
        raise ValueError("Ed25519 required") from None
    if not isinstance(key, ed25519.Ed25519PublicKey):
        raise ValueError("Ed25519 required")
    canonical = key.public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
    if canonical != value:
        raise ValueError("non-canonical key")
    return value


def fingerprint(key: str) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(base64.b64decode(key.split()[1])).digest()).decode().rstrip("=")


class PairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    expires: int
    label: str = Field(min_length=1, max_length=64, pattern=r"^[\w .@-]+$")
    ssh_key: str = Field(max_length=256)
    exchange_key: str = Field(min_length=43, max_length=43)
    return_origin: str = Field(default="", max_length=64)

    @field_validator("return_origin")
    @classmethod
    def valid_return_origin(cls, value: str) -> str:
        return local_return_origin(value)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if str(uuid.UUID(value)) != value:
            raise ValueError("invalid id")
        return value

    @field_validator("ssh_key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        return public_key(value)

    @field_validator("exchange_key")
    @classmethod
    def valid_exchange(cls, value: str) -> str:
        x25519.X25519PublicKey.from_public_bytes(decode(value))
        return value

    def check_expiry(self) -> None:
        if not time.time() < self.expires <= time.time() + _TTL + 60:
            raise RemoteError("pair_expired")


def read_request(value: str) -> PairRequest:
    try:
        request = PairRequest.model_validate(unpack("nbpr1.", value))
        request.check_expiry()
        return request
    except (ValidationError, ValueError):
        raise RemoteError("pair_invalid") from None


class PairReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    ssh_key: str
    host: str = Field(min_length=1, max_length=253, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9.:-]*$")
    user: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z_][a-zA-Z0-9_-]*$")
    ssh_port: int = Field(ge=1, le=65535)
    host_key: str
    hostname: str = Field(min_length=1, max_length=253)
    config_path: str = Field(min_length=1, max_length=2048)
    port: int = Field(ge=1, le=65535)
    secret: str = Field(min_length=1, max_length=4096, repr=False)
    token_issue_path: str = Field(default="", max_length=2048)
    authorized_until: int

    @field_validator("host_key", "ssh_key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        return public_key(value)

    def preview(self) -> dict[str, Any]:
        return {"id": self.id, "host": f"{self.user}@{self.host}", "port": self.ssh_port,
                "hostname": self.hostname, "fingerprint": fingerprint(self.host_key),
                "authorized_until": self.authorized_until,
                "revoke_command": f"nanobot remote revoke {self.id} --ssh-user {self.user}"}

    def destination(self) -> tuple[str, str, int, str, str, int, str, str]:
        """Conservative same-instance evidence, confined to the local manager.

        A name/IP or the restart-scoped gateway ID is not enough. Require the
        same pinned SSH server, account, resolved config and WebUI capability.
        Keep changed credentials/addresses separate rather than guessing. Never
        send this tuple (or a credential-derived hash) to the browser.
        """
        return (self.host, self.user, self.ssh_port, self.host_key, self.config_path,
                self.port, self.secret, self.token_issue_path)


def _derive(shared: bytes, request_id: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=request_id.encode(), info=_CONTEXT).derive(shared)


def seal(request: PairRequest, receipt: PairReceipt) -> str:
    private = x25519.X25519PrivateKey.generate()
    peer = x25519.X25519PublicKey.from_public_bytes(decode(request.exchange_key))
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(_derive(private.exchange(peer), request.id)).encrypt(
        nonce, receipt.model_dump_json().encode(), _CONTEXT + request.id.encode(),
    )
    return pack("nbpc1.", {"id": request.id, "key": encode(private.public_key().public_bytes_raw()),
                            "nonce": encode(nonce), "data": encode(encrypted)})


def private_write(path: Path, content: bytes) -> None:
    # Callers own the private parent directory. Never overwrite or follow links.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


class PairStore:
    def __init__(self, directory: Path) -> None:
        self.root = directory / "remote-pairing"

    def path(self, key: str) -> Path:
        try:
            if str(uuid.UUID(key)) != key:
                raise ValueError
        except (ValueError, AttributeError):
            raise RemoteError("pair_invalid") from None
        return self.root / key

    def start(self, return_origin: str = "") -> dict[str, Any]:
        try:
            return_origin = local_return_origin(return_origin)
        except (ValueError, TypeError):
            raise RemoteError("pair_invalid") from None
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise RemoteError("local_io_error")
        self.root.chmod(0o700)
        # Bound abandoned requests without deleting completed device identities.
        pending = 0
        for path in self.root.iterdir():
            if path.is_dir() and not (path / "receipt").exists():
                if path.stat().st_mtime < time.time() - _TTL:
                    self.cancel(path.name)
                else:
                    pending += 1
        if pending >= 8:
            raise RemoteError("pair_limit")
        key = str(uuid.uuid4())
        path = self.path(key)
        path.mkdir(mode=0o700)
        ssh = ed25519.Ed25519PrivateKey.generate()
        exchange = x25519.X25519PrivateKey.generate()
        request = PairRequest(id=key, expires=int(time.time()) + _TTL,
                              label="".join(c for c in socket.gethostname() if c.isalnum() or c in ".-_")[:64] or "Computer",
                              ssh_key=ssh.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode(),
                              exchange_key=encode(exchange.public_key().public_bytes_raw()),
                              return_origin=return_origin)
        private_write(path / "identity", ssh.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()))
        private_write(path / "exchange", exchange.private_bytes_raw())
        private_write(path / "request", request.model_dump_json().encode())
        return {"id": key, "expires": request.expires,
                "command": "nanobot remote pair " + pack("nbpr1.", request.model_dump(exclude_defaults=True))}

    def _decrypt(self, key: str, code: str, *, pending: bool, require_active: bool = True) -> PairReceipt:
        path = self.path(key)
        try:
            request = PairRequest.model_validate_json((path / "request").read_bytes())
            if pending:
                request.check_expiry()
            envelope = unpack("nbpc1.", code)
            if envelope.get("id") != key:
                raise ValueError
            private = x25519.X25519PrivateKey.from_private_bytes((path / "exchange").read_bytes())
            peer = x25519.X25519PublicKey.from_public_bytes(decode(envelope["key"]))
            clear = AESGCM(_derive(private.exchange(peer), key)).decrypt(
                decode(envelope["nonce"]), decode(envelope["data"]), _CONTEXT + key.encode(),
            )
            receipt = PairReceipt.model_validate_json(clear)
            if receipt.id != key or receipt.ssh_key != request.ssh_key:
                raise ValueError
            if require_active and receipt.authorized_until <= time.time():
                raise RemoteError("pair_authorization_expired")
            return receipt
        except (OSError, ValueError, TypeError, KeyError, InvalidTag):
            raise RemoteError("pair_invalid") from None

    def preview(self, key: str, code: str) -> dict[str, Any]:
        return self._decrypt(key, code, pending=True).preview()

    def review(self, key: str, code: str) -> PairReceipt:
        return self._decrypt(key, code, pending=True)

    def saved_receipt(self, key: str) -> PairReceipt | None:
        """Read grouping evidence, even for expired grants, without granting access."""
        try:
            code = (self.path(key) / "receipt").read_text()
            return self._decrypt(key, code, pending=False, require_active=False)
        except (OSError, RemoteError):
            return None

    def finish(self, key: str, code: str) -> PairReceipt:
        receipt = self._decrypt(key, code, pending=True)
        path = self.path(key) / "receipt"
        if path.exists():
            if path.read_text() != code:
                raise RemoteError("pair_used")
        else:
            private_write(path, code.encode())
        return receipt

    def connection(self, key: str) -> dict[str, Any]:
        try:
            code = (self.path(key) / "receipt").read_text()
        except OSError:
            raise RemoteError("pair_invalid") from None
        return self._decrypt(key, code, pending=False).model_dump()

    def authorization_until(self, key: str) -> int | None:
        """Expose only the expiry for display, including already-expired grants.

        Connecting still goes through connection(), which rejects expired grants.
        A missing/unreadable receipt must not hide every other saved server.
        """
        try:
            code = (self.path(key) / "receipt").read_text()
            return self._decrypt(key, code, pending=False, require_active=False).authorized_until
        except (OSError, RemoteError):
            return None

    def cancel(self, key: str) -> None:
        path = self.path(key)
        if path.is_symlink() or (path / "receipt").exists():
            return
        for name in ("identity", "exchange", "request"):
            (path / name).unlink(missing_ok=True)
        if path.exists():
            path.rmdir()

    def forget(self, key: str) -> None:
        """Destroy only this managed local identity; server revocation is separate."""
        path = self.path(key)
        if path.is_symlink():
            raise RemoteError("local_io_error")
        for name in ("identity", "exchange", "request", "receipt", "ssh_route"):
            (path / name).unlink(missing_ok=True)
        if path.exists():
            path.rmdir()

    def profile(self, receipt: PairReceipt, ssh_config: str = "") -> RemoteProfile:
        return RemoteProfile(name=receipt.hostname[:64], host=f"{receipt.user}@{receipt.host}",
                             port=receipt.ssh_port, config_path=receipt.config_path,
                             identity_file=str(self.path(receipt.id) / "identity"),
                             ssh_config=ssh_config)
