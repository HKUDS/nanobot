"""Local macOS native-host distribution and private, bounded transport.

This is an explicitly staged developer build, not a substitute for an upstream
signed release. Only local installation code can register its archive. No WebUI
or model-facing operation accepts an executable path or download URL.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any, cast

REVISION = "d27f6a89d8aeef0f56363ee9bb60bbc565912b1e"
VERSION = "0.1.0"
APP = "nanobot Computer Use.app"
PERMISSION_APP = "nanobot Computer Use"
CAPABILITY = "webui.computer-use-native.v1"
MAX_RESPONSE = 32 * 1024 * 1024


def package_digest(root: Path) -> str | None:
    marker = root / "native-package.json"
    if not marker.exists():
        return None
    decoded = json.loads(marker.read_text())
    if not isinstance(decoded, dict):
        raise ValueError("The local Computer Use build manifest is invalid. Rebuild and stage it locally.")
    value = cast(dict[str, Any], decoded)
    if (value.get("schema") != 1 or value.get("revision") != REVISION
            or value.get("version") != VERSION or not isinstance(value.get("sha256"), str)
            or value.get("architecture") != platform.machine().lower()
            or len(value["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in value["sha256"])):
        raise ValueError("The local Computer Use build manifest is invalid. Rebuild and stage it locally.")
    return value["sha256"]


def register_package(config_path: Path, manifest_path: Path) -> None:
    """Stage a locally built archive for the ordinary install/uninstall UI."""
    from nanobot.apps.cua_driver import CuaDriver
    from nanobot.config.loader import load_config

    if "cua-driver" in load_config(config_path).tools.mcp_servers:
        raise ValueError("Disable Computer Use before selecting a different native build.")
    previous = CuaDriver(config_path)
    if previous.release and previous.directory.exists():
        raise ValueError("Uninstall the current Computer Use driver before selecting a different native build.")
    source = json.loads(manifest_path.read_text())
    if (source.get("revision") != REVISION or source.get("version") != VERSION
            or source.get("architecture") != platform.machine().lower()):
        raise ValueError("The native build does not match the pinned source.")
    archive = Path(source["archive"]).resolve()
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != source.get("sha256"):
        raise ValueError("The native build checksum does not match.")
    root = config_path.resolve().parent / "apps/cua-driver"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not root.resolve().is_relative_to(config_path.resolve().parent):
        raise ValueError("Managed directory is redirected.")
    if (root / "nanobot-computer-use-0.1.0-darwin").exists():
        raise ValueError("Uninstall the previous native build before staging a replacement.")
    # Staging is explicit local developer administration, never a remote action.
    with tempfile.TemporaryDirectory(prefix="native-stage-", dir=root) as temporary:
        staging = Path(temporary)
        shutil.copyfile(archive, staging / "native-package.tar.gz")
        (staging / "native-package.json").write_text(json.dumps({
            "schema": 1, "version": VERSION, "revision": REVISION, "sha256": digest,
            "architecture": source["architecture"],
        }))
        os.replace(staging / "native-package.tar.gz", root / "native-package.tar.gz")
        os.replace(staging / "native-package.json", root / "native-package.json")


class NativeConnection:
    """One serialized native channel; closing it releases its window lease."""
    def __init__(self, path: Path):
        self.path = path
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.lock = asyncio.Lock()

    async def request(self, method: str, *, name: str = "", arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self.lock:
            if self.writer is None:
                self.reader, self.writer = await asyncio.open_unix_connection(self.path, limit=MAX_RESPONSE)
            try:
                self.writer.write(json.dumps({"method": method, "name": name, "arguments": arguments or {}}).encode() + b"\n")
                await self.writer.drain()
                assert self.reader is not None
                line = await asyncio.wait_for(self.reader.readline(), timeout=55)
                decoded = json.loads(line)
                if not isinstance(decoded, dict):
                    raise ValueError("Invalid native host response.")
                reply = cast(dict[str, Any], decoded)
                if type(reply.get("ok")) is not bool:
                    raise ValueError("Invalid native host response.")
                if not reply["ok"]:
                    raise RuntimeError(str(reply.get("error", "Native operation failed.")))
                if not isinstance(reply.get("result"), dict):
                    raise ValueError("Invalid native host result.")
                return reply["result"]
            except BaseException:
                # No replay after cancellation or ambiguous input completion.
                await self.close()
                raise

    async def close(self) -> None:
        writer, self.writer, self.reader = self.writer, None, None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass


async def admin(path: Path, method: str, name: str = "") -> dict[str, Any]:
    connection = NativeConnection(path)
    try:
        return await connection.request(method, name=name)
    finally:
        await connection.close()


def stop(path: Path) -> None:
    asyncio.run(admin(path, "stop"))


def clear_pause(address: Path) -> None:
    """User-settings-only recovery. No tool or MCP reconnect calls this."""
    marker = address.with_suffix(".paused")
    if marker.exists():
        info = marker.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("Native pause marker is not owned by this user.")
        marker.unlink()
