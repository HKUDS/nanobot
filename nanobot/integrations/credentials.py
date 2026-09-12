"""Private local write-only credential storage and fixed consumer command.

Not encryption: use host disk protection and a trusted administrator account.
Only the CLI's explicit consumer invocation emits a secret to its stdout pipe.
"""
from __future__ import annotations

import argparse
import os
import re
import stat
import tempfile
import uuid
from pathlib import Path


class PrivateStoreError(RuntimeError):
    pass


def private_path(workspace: Path, relative: str) -> Path:
    root = workspace.expanduser().resolve()
    candidate = root / relative
    current = root
    for part in Path(relative).parts:
        if part in {"..", "."}:
            raise PrivateStoreError("Unsafe integration path")
        current = current / part
        if current.is_symlink():
            raise PrivateStoreError("Integration paths must not be symbolic links")
    if not candidate.resolve(strict=False).is_relative_to(root):
        raise PrivateStoreError("Integration path is outside workspace")
    return candidate


def atomic_private_write(path: Path, content: bytes) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise PrivateStoreError("Unsafe integration path")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt" and stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise PrivateStoreError("Integration directory must be private (0700)")
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.chmod(name, 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class CredentialStore:
    def __init__(self, workspace: Path):
        self.workspace = workspace

    def path(self, reference: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", reference):
            raise PrivateStoreError("Invalid credential reference")
        return private_path(self.workspace, f".nanobot/integrations/secrets/{reference}")

    def configured(self, reference: str) -> bool:
        return bool(reference) and self.path(reference).is_file()

    def put(self, value: str) -> str:
        if not value or len(value) > 4096 or any(c in value for c in "\r\n\x00"):
            raise PrivateStoreError("Invalid credential format")
        root = private_path(self.workspace, ".nanobot/integrations")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt" and root.stat().st_mode & 0o077:
            raise PrivateStoreError("Integration directory must be private (0700)")
        reference = uuid.uuid4().hex
        atomic_private_write(self.path(reference), value.encode("utf-8"))
        return reference

    def get(self, reference: str) -> str:
        path = self.path(reference)
        if os.name != "nt" and (path.stat().st_mode & 0o077 or path.parent.stat().st_mode & 0o077):
            raise PrivateStoreError("Credential permissions are not private")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            raw = handle.read(4097)
        if len(raw) > 4096:
            raise PrivateStoreError("Invalid credential size")
        return raw.decode("utf-8")

    def discard_uncommitted(self, reference: str) -> None:
        self.path(reference).unlink(missing_ok=True)


def icloud_credentials(config_path: Path) -> tuple[str, str, str]:
    from nanobot.config.loader import load_config
    config = load_config(config_path)
    icloud = config.personal_integrations.icloud
    if not icloud.username or not icloud.credential_ref:
        raise PrivateStoreError("iCloud credentials are not configured")
    return (icloud.username, CredentialStore(config.workspace_path).get(icloud.credential_ref),
            "https://caldav.icloud.com/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read a credential for a configured local consumer")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--ref", required=True)
    args = parser.parse_args()
    try:
        value = CredentialStore(args.workspace).get(args.ref)
    except Exception:
        parser.exit(1, "Credential unavailable; check private store and permissions.\n")
    print(value, end="")


if __name__ == "__main__":
    main()
