"""A managed stdio launch, not a second agent runtime.

The upstream macOS launcher selects /Applications by name. Use the exact
nanobot-managed bundle and private socket instead, so another agent's daemon
is neither selected nor stopped. No OS grants are made by this launcher.
"""

from __future__ import annotations

import hashlib
import os
import platform
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

from filelock import FileLock

from nanobot.apps.cua_driver import DRIVER_ENV, NAME, CuaDriver, DriverError
from nanobot.config.loader import load_config


def endpoint(config_path: Path) -> Path:
    # Unix-domain endpoints have a short path limit, even when the data dir
    # lives under a long application-support path. Never share a world-readable
    # socket directory or follow a pre-created symlink.
    key = hashlib.sha256(str(config_path.resolve()).encode()).hexdigest()[:20]
    # MCP stdio deliberately filters inherited environment variables, including
    # TMPDIR. Use the same short macOS location in both gateway and child.
    root = Path("/tmp") / f"nb-cua-{os.getuid()}-{key}"
    root.mkdir(mode=0o700, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise DriverError("Cua Driver's socket directory is not private to this user.")
    return root / ("native.sock" if CuaDriver(config_path).native else "driver.sock")


def daemon_listening(path: Path) -> bool:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(0.2)
        try:
            client.connect(str(path))
            return True
        except OSError:
            return False


def _require_enabled(driver: CuaDriver) -> None:
    configured = load_config(driver.config_path).tools.mcp_servers.get(NAME)
    if configured is None or not driver.owns(configured):
        raise DriverError("Managed desktop access is disabled. Enable it in Apps before connecting.")


def stop_daemon(driver: CuaDriver) -> None:
    """Serialize stopping with any launcher already waiting for this socket."""
    address = endpoint(driver.config_path)
    with FileLock(str(address.with_suffix(".lock")), timeout=20):
        if not daemon_listening(address):
            return
        if driver.native:
            from nanobot.apps.computer_use_native import stop

            stop(address)
            deadline = time.monotonic() + 5
            while daemon_listening(address):
                if time.monotonic() > deadline:
                    raise DriverError("Computer Use did not stop; its installation has been kept.")
                time.sleep(0.05)
            return
        try:
            subprocess.run(
                [str(driver.executable), "stop", "--socket", str(address)],
                env={**os.environ, **DRIVER_ENV}, timeout=10, check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise DriverError("Could not stop the managed driver. Check Cua Driver on the gateway computer.") from exc


def ensure_daemon(driver: CuaDriver, *, check: bool = False) -> Path:
    """One native startup owns permission prompts, shared by setup and MCP.

    The pinned daemon binds its socket before waiting for OS grants. Reuse
    that instance while the user answers; a second permission helper would
    request the same grants concurrently with the daemon's startup gate.
    """
    address = endpoint(driver.config_path)
    with FileLock(str(address.with_suffix(".lock")), timeout=20):
        if not check:
            # Disable can win while a launcher waits for the lifecycle lock.
            _require_enabled(driver)
        if not daemon_listening(address):
            if check:
                raise DriverError("The managed driver is not running; enable it before checking permissions.")
            if driver.native and address.with_suffix(".paused").exists():
                raise DriverError("Sharing was stopped. Reconnect Computer Use in Apps before starting another task.")
            command = ["/usr/bin/open", "-n", "-g"]
            for key, value in DRIVER_ENV.items():
                command.extend(["--env", f"{key}={value}"])
            if driver.native:
                configured = load_config(driver.config_path).tools.mcp_servers[NAME]
                mode = "control" if "click" in configured.enabled_tools else "observe"
                command.extend(["-a", str(driver.bundle), "--args", "--socket", str(address), "--mode", mode])
            else:
                command.extend([
                    "-a", str(driver.bundle), "--args", "serve",
                    "--socket", str(address), "--pid-file", str(address.with_suffix(".pid")),
                ])
            subprocess.run(command, check=True, timeout=15, stdout=subprocess.DEVNULL)
            deadline = time.monotonic() + 15
            while not daemon_listening(address):
                if time.monotonic() > deadline:
                    raise DriverError("Cua Driver did not start. Check system permissions on the gateway computer.")
                time.sleep(0.1)
    return address


def launch(config_path: Path, *, check: bool = False) -> int:
    driver = CuaDriver(config_path)
    if not driver.installed():
        raise DriverError("The managed Cua Driver package is not installed.")
    if not check:
        # A stale MCP wrapper may try reconnecting after Disable, especially
        # when runtime refresh failed. Persisted access owns the launch decision.
        _require_enabled(driver)
    env = {**os.environ, **DRIVER_ENV}
    args = [str(driver.executable), "mcp"]
    if platform.system() == "Darwin":
        address = ensure_daemon(driver, check=check)
        if driver.native:
            import asyncio

            from nanobot.apps.computer_use_mcp import serve

            asyncio.run(serve(address))
            return 0
        # The proxy never owns OS grants or auto-launches another app. The
        # exact installed CuaDriver app above owns the daemon's TCC identity.
        args.extend(["--embedded", "--socket", str(address)])
    if os.name == "nt":
        # Windows has no POSIX exec replacement; stdio remains inherited.
        return subprocess.call(args, env=env)
    os.execve(driver.executable, args, env)
    return 0


if __name__ == "__main__":
    try:
        if len(sys.argv) not in {2, 3} or (len(sys.argv) == 3 and sys.argv[2] != "--check"):
            raise DriverError("Usage: python -m nanobot.apps.cua_driver_stdio CONFIG_PATH [--check]")
        sys.exit(launch(Path(sys.argv[1]), check=len(sys.argv) == 3))
    except (DriverError, OSError, subprocess.SubprocessError) as exc:
        print(f"nanobot: {exc}", file=sys.stderr)
        sys.exit(1)
