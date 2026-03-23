"""Tirith pre-exec security scanning wrapper.

Tirith (https://github.com/sheeki03/tirith) is a terminal security tool
that scans commands for content-level threats: homograph/punycode URLs,
pipe-to-interpreter patterns, terminal injection (ANSI escapes, bidi
Unicode, zero-width chars), typosquatted packages, and insecure transport.

Exit code is the verdict source of truth:
  0 = allow, 1 = block, 2 = warn

Auto-install: if tirith is not found on PATH or at the configured path,
it is downloaded from GitHub releases with SHA-256 checksum verification.
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import zipfile
from typing import Any

logger = logging.getLogger(__name__)

_REPO = "sheeki03/tirith"
_MARKER_TTL = 86400  # 24h

# Module-level cache
_resolved_path: str | None = None
_INSTALL_FAILED = object()
_install_failure_reason: str = ""
_install_lock = threading.Lock()
_install_thread: threading.Thread | None = None


def _nanobot_bin_dir() -> str:
    d = os.path.join(os.path.expanduser("~"), ".nanobot", "bin")
    os.makedirs(d, exist_ok=True)
    return d


def _failure_marker_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".nanobot", ".tirith-install-failed")


def _is_install_failed_on_disk() -> bool:
    try:
        p = _failure_marker_path()
        mtime = os.path.getmtime(p)
        return (time.time() - mtime) < _MARKER_TTL
    except OSError:
        return False


def _mark_install_failed(reason: str = ""):
    try:
        p = _failure_marker_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(reason)
    except OSError:
        pass


def _clear_install_failed():
    try:
        os.unlink(_failure_marker_path())
    except OSError:
        pass


def _detect_target() -> tuple[str, str] | None:
    """Return (target_triple, archive_ext) for the current platform."""
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Darwin":
        plat = "apple-darwin"
    elif system == "Linux":
        plat = "unknown-linux-gnu"
    elif system == "Windows":
        plat = "pc-windows-msvc"
    else:
        return None

    if machine in ("x86_64", "amd64"):
        arch = "x86_64"
    elif machine in ("aarch64", "arm64"):
        arch = "aarch64"
    else:
        return None

    ext = ".zip" if system == "Windows" else ".tar.gz"
    return f"{arch}-{plat}", ext


def _download_file(url: str, dest: str, timeout: int = 30):
    import urllib.request

    req = urllib.request.Request(url)
    token = os.getenv("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def _verify_checksum(archive_path: str, checksums_path: str, archive_name: str) -> bool:
    expected = None
    with open(checksums_path) as f:
        for line in f:
            parts = line.strip().split("  ", 1)
            if len(parts) == 2 and parts[1] == archive_name:
                expected = parts[0]
                break
    if not expected:
        logger.warning("No checksum entry for %s", archive_name)
        return False

    sha = hashlib.sha256()
    with open(archive_path, "rb") as fb:
        for chunk in iter(lambda: fb.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest() == expected


def _install_tirith(*, log_failures: bool = True) -> tuple[str | None, str]:
    log = logger.warning if log_failures else logger.debug

    result = _detect_target()
    if not result:
        log("tirith: unsupported platform %s/%s", platform.system(), platform.machine())
        return None, "unsupported_platform"

    target, ext = result
    archive_name = f"tirith-{target}{ext}"
    base_url = f"https://github.com/{_REPO}/releases/latest/download"

    tmpdir = tempfile.mkdtemp(prefix="tirith-install-")
    try:
        archive_path = os.path.join(tmpdir, archive_name)
        checksums_path = os.path.join(tmpdir, "checksums.txt")

        logger.info("tirith not found — downloading for %s...", target)

        try:
            _download_file(f"{base_url}/{archive_name}", archive_path)
            _download_file(f"{base_url}/checksums.txt", checksums_path)
        except Exception as exc:
            log("tirith download failed: %s", exc, exc_info=True)
            return None, "download_failed"

        if not _verify_checksum(archive_path, checksums_path, archive_name):
            log("tirith checksum mismatch")
            return None, "checksum_failed"

        # Extract binary
        bin_name = "tirith.exe" if platform.system() == "Windows" else "tirith"
        if ext == ".zip":
            with zipfile.ZipFile(archive_path) as zf:
                for name in zf.namelist():
                    if name == bin_name or name.endswith(f"/{bin_name}"):
                        zf.extract(name, tmpdir)
                        src = os.path.join(tmpdir, name)
                        break
                else:
                    return None, "binary_not_in_archive"
        else:
            with tarfile.open(archive_path, "r:gz") as tar:
                for member in tar.getmembers():
                    if (member.name == "tirith" or member.name.endswith("/tirith")) and ".." not in member.name:
                        member.name = "tirith"
                        tar.extract(member, tmpdir)
                        break
                else:
                    return None, "binary_not_in_archive"
            src = os.path.join(tmpdir, "tirith")

        dest = os.path.join(_nanobot_bin_dir(), bin_name)
        shutil.move(src, dest)
        os.chmod(dest, os.stat(dest).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        logger.info("tirith installed to %s (SHA-256 verified)", dest)
        return dest, ""
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _resolve_tirith_path(configured: str = "tirith") -> str:
    global _resolved_path, _install_failure_reason

    if _resolved_path is not None and _resolved_path is not _INSTALL_FAILED:
        return _resolved_path

    explicit = configured != "tirith"
    expanded = os.path.expanduser(configured)

    if explicit:
        found = shutil.which(expanded) if not os.path.isfile(expanded) else expanded
        if found:
            _resolved_path = found
            return found
        _resolved_path = _INSTALL_FAILED
        return expanded

    # Default: PATH → ~/.nanobot/bin → auto-install
    found = shutil.which("tirith")
    if found:
        _resolved_path = found
        _clear_install_failed()
        return found

    bin_name = "tirith.exe" if sys.platform == "win32" else "tirith"
    local_bin = os.path.join(_nanobot_bin_dir(), bin_name)
    if os.path.isfile(local_bin) and os.access(local_bin, os.X_OK):
        _resolved_path = local_bin
        _clear_install_failed()
        return local_bin

    if _resolved_path is _INSTALL_FAILED or _is_install_failed_on_disk():
        return expanded

    with _install_lock:
        # Re-check after acquiring lock (another thread may have resolved)
        if _resolved_path is not None and _resolved_path is not _INSTALL_FAILED:
            return _resolved_path

        found = shutil.which("tirith")
        if found:
            _resolved_path = found
            _clear_install_failed()
            return found

        local_bin = os.path.join(_nanobot_bin_dir(), bin_name)
        if os.path.isfile(local_bin) and os.access(local_bin, os.X_OK):
            _resolved_path = local_bin
            _clear_install_failed()
            return local_bin

        # Re-check failure state inside lock — a previous waiter may have
        # already failed while we were queued.
        if _resolved_path is _INSTALL_FAILED or _is_install_failed_on_disk():
            return expanded

        installed, reason = _install_tirith()
        if installed:
            _resolved_path = installed
            _clear_install_failed()
            return installed

        _resolved_path = _INSTALL_FAILED
        _install_failure_reason = reason
        _mark_install_failed(reason)
        return expanded


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

_MAX_FINDINGS = 50


def check_security(
    text: str,
    context: str = "exec",
    *,
    enabled: bool = True,
    tirith_bin: str = "tirith",
    timeout: int = 5,
    fail_open: bool = True,
) -> dict[str, Any]:
    """Run tirith scan. Returns {action, findings, summary}.

    Exit code is source of truth: 0=allow, 1=block, 2=warn.
    """
    if not enabled:
        return {"action": "allow", "findings": [], "summary": ""}

    tirith_path = _resolve_tirith_path(tirith_bin)

    # Platform-aware shell mode
    shell_mode = "posix" if sys.platform != "win32" else "cmd"

    try:
        if context == "exec":
            cmd = [
                tirith_path, "check", "--json", "--non-interactive",
                "--shell", shell_mode, "--", text,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        else:
            cmd = [tirith_path, "paste", "--json", "--non-interactive"]
            result = subprocess.run(
                cmd, input=text, capture_output=True, text=True, timeout=timeout,
            )
    except OSError as exc:
        logger.warning("tirith spawn failed: %s", exc, exc_info=True)
        if fail_open:
            return {"action": "allow", "findings": [], "summary": f"tirith unavailable: {exc}"}
        return {"action": "block", "findings": [], "summary": f"tirith failed (fail-closed): {exc}"}
    except subprocess.TimeoutExpired:
        logger.warning("tirith timed out after %ds", timeout)
        if fail_open:
            return {"action": "allow", "findings": [], "summary": f"tirith timed out ({timeout}s)"}
        return {"action": "block", "findings": [], "summary": "tirith timed out (fail-closed)"}

    exit_code = result.returncode
    if exit_code == 0:
        action = "allow"
    elif exit_code == 1:
        action = "block"
    elif exit_code == 2:
        action = "warn"
    else:
        logger.warning("tirith unexpected exit code %d", exit_code)
        if fail_open:
            return {"action": "allow", "findings": [], "summary": f"tirith exit code {exit_code} (fail-open)"}
        return {"action": "block", "findings": [], "summary": f"tirith exit code {exit_code} (fail-closed)"}

    import json

    findings: list[dict[str, Any]] = []
    summary = ""
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else {}
        findings = data.get("findings", [])[:_MAX_FINDINGS]
        summary = (data.get("summary", "") or "")[:500]
    except (json.JSONDecodeError, AttributeError):
        logger.debug("tirith JSON parse failed, using exit code only")
        if action == "block":
            summary = "security issue detected (details unavailable)"
        elif action == "warn":
            summary = "security warning detected (details unavailable)"

    return {"action": action, "findings": findings, "summary": summary}
