"""Provision the Bun runtime used by source installations and package builds."""

from __future__ import annotations

import hashlib
import io
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock

BUN_VERSION = "1.3.13"
# SHA-256 of the official bun-v1.3.13 release archives.
_ARCHIVES = {
    "linux-x64-baseline": "9d8a24292a7068090205daac0a5a223f5f69736f5287e37bf88d3b4031edc750",
    "linux-x64-musl-baseline": "88ca7c7ad235b498f549eea2f770f434e9f0f5e9ba95168a2d3a1f235184c394",
    "linux-aarch64": "70bae41b3908b0a120e1e58c5c8af30e74afae3b8d11b0d3fdd8e787ddfb4b22",
    "linux-aarch64-musl": "5385e978107ce4934298d8d6afe9bfbb898683f6cc23e6753a0da60bc60c5b81",
    "darwin-x64-baseline": "a98ba6a480f22fda9b343626b906a4e26aa53618bf85d2bc5928ecf2ba45f0ed",
    "darwin-aarch64": "5467e3f65dba526b9fea98f0cce04efafc0c63e169733ec27b876a3ad32da190",
    "windows-x64-baseline": "c68c7903c1190101590cc1b2129835f47211b3b37ae87759f2b97d6534aa3ad1",
}


class BunUnavailableError(RuntimeError):
    """The required runtime could not be prepared for this platform."""


@contextmanager
def bun_environment(executable: str) -> Generator[dict[str, str]]:
    """Run lifecycle scripts' `node` commands with Bun, without a global Node shim."""
    env = os.environ.copy()
    runtime = Path(shutil.which(executable) or executable).resolve()
    if os.name == "nt" and runtime.suffix.lower() in {".cmd", ".bat"}:
        runtime = Path(subprocess.check_output(
            [str(runtime), "-p", "process.execPath"], text=True, timeout=10,
        ).strip())
    # `bun --bun install` does not alias node in dependency lifecycle scripts.
    # Only this subprocess tree sees the alias; Windows hardlinks need no admin rights.
    with tempfile.TemporaryDirectory(prefix="nanobot-bun-") as temporary:
        node = Path(temporary) / ("node.exe" if os.name == "nt" else "node")
        try:
            node.hardlink_to(runtime)
        except OSError:
            shutil.copy2(runtime, node)
        env["PATH"] = os.pathsep.join((temporary, str(runtime.parent), env.get("PATH", "")))
        yield env


def _matches_version(executable: str) -> bool:
    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() == BUN_VERSION
    except (OSError, subprocess.TimeoutExpired):
        return False


def _target() -> str:
    system = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}.get(
        platform.system(), "unknown",
    )
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "aarch64", "aarch64": "aarch64"}.get(
        platform.machine().lower(), "unknown",
    )
    musl = system == "linux" and (
        platform.libc_ver()[0] == "musl" or any(Path("/lib").glob("ld-musl-*.so.1"))
    )
    target = f"{system}-{arch}" + ("-musl" if musl else "")
    if arch == "x64":
        target += "-baseline"
    if target not in _ARCHIVES:
        raise BunUnavailableError(f"Automatic Bun setup is not supported on {system}/{arch}.")
    return target


def ensure_bun(
    *, cache_dir: Path | None = None, output: Callable[[str], None] = print,
) -> str:
    """Return the pinned runtime, downloading a verified executable when missing."""
    existing = shutil.which("bun")
    if existing and _matches_version(existing):
        return existing
    target = _target()
    root = cache_dir or Path.home() / ".nanobot" / "tools" / "bun"
    directory = root / BUN_VERSION / target
    executable = directory / ("bun.exe" if os.name == "nt" else "bun")
    directory.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory / "install.lock"), timeout=180):
        if executable.is_file() and _matches_version(str(executable)):
            return str(executable)
        output(f"Downloading Bun {BUN_VERSION} ({target})…")
        url = f"https://github.com/oven-sh/bun/releases/download/bun-v{BUN_VERSION}/bun-{target}.zip"
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                raw = response.read(128 * 1024 * 1024 + 1)
            if hashlib.sha256(raw).hexdigest() != _ARCHIVES[target]:
                raise BunUnavailableError("Bun download failed checksum verification. Retry the download.")
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                member = archive.getinfo(f"bun-{target}/{executable.name}")
                if member.file_size > 256 * 1024 * 1024:
                    raise BunUnavailableError("Bun archive contains an oversized executable.")
                content = archive.read(member)
            with tempfile.TemporaryDirectory(prefix=".install-", dir=directory) as temporary:
                candidate = Path(temporary) / executable.name
                candidate.write_bytes(content)
                candidate.chmod(0o755)
                if not _matches_version(str(candidate)):
                    raise BunUnavailableError("Downloaded Bun cannot run on this system.")
                os.replace(candidate, executable)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            raise BunUnavailableError(f"Could not prepare Bun {BUN_VERSION}: {exc}") from exc
    return str(executable)
