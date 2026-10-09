"""Install a pinned Cua Driver release without changing other agents or PATH.

Installation is inert. Only an explicitly enabled MCP connection starts the
driver; macOS retains the signed app's own permission identity.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, NotRequired, TypedDict, cast

import httpx
from filelock import FileLock, Timeout

from nanobot.config.schema import MCPServerConfig
from nanobot.security.network import PinnedDNSAsyncTransport

NAME = "cua-driver"
CAPABILITY = "webui.cua-driver.v1"
SETUP_CAPABILITY = "webui.cua-driver-guided-setup.v1"
PERMISSIONS_CAPABILITY = "webui.cua-driver-permission-request.v1"
RECONNECT_CAPABILITY = "webui.cua-driver-reconnect.v1"
UNINSTALL_CAPABILITY = "webui.cua-driver-uninstall.v1"
UNINSTALL_RESET_CAPABILITY = "webui.computer-use-uninstall-reset.v1"
VERSION = "0.33.4"
DOCS_URL = "https://cua.ai/docs/cua-driver/quickstart"
_BASE_URL = f"https://github.com/trycua/cua/releases/download/cua-driver-rs-v{VERSION}/"
_MAX_DOWNLOAD = 200 * 1024 * 1024
_MAX_UNPACKED = 1024 * 1024 * 1024
DRIVER_ENV = {
    "CUA_DRIVER_RS_TELEMETRY_ENABLED": "0", "DO_NOT_TRACK": "1",
    "CUA_DRIVER_RS_UPDATE_CHECK": "0",
}
OBSERVE_TOOLS = ["list_windows", "get_window_state", "get_accessibility_tree", "zoom"]
CONTROL_TOOLS = OBSERVE_TOOLS + [
    "click", "double_click", "right_click", "scroll", "drag", "move_cursor",
    "type_text", "press_key", "hotkey", "set_value", "bring_to_front",
]


class DriverError(Exception):
    """An actionable setup failure, safe to return through settings."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Release:
    target: str
    digest: str
    native: bool = False

    @property
    def directory(self) -> str:
        if self.native:
            return "nanobot-computer-use-0.1.0-darwin"
        return f"cua-driver-rs-{VERSION}-{self.target}"

    @property
    def filename(self) -> str:
        return self.directory + (".zip" if self.target.startswith("windows-") else ".tar.gz")

    @property
    def executable(self) -> str:
        if self.native:
            return "nanobot Computer Use.app/Contents/MacOS/nanobot-computer-use"
        if self.target.startswith("darwin-"):
            return "CuaDriver.app/Contents/MacOS/cua-driver"
        return "cua-driver.exe" if self.target.startswith("windows-") else "cua-driver"


# These are the upstream checksums for this exact release, not a mutable
# latest-release URL. Adding/upgrading a release requires reviewing its hashes.
_RELEASES = {
    "darwin-universal": Release("darwin-universal", "bf90ac5db76f44baff47e256cb7355959be3e8df3706b9d178505720f02d74c1"),
    "linux-x86_64": Release("linux-x86_64", "a4759cc41c00691a345f08abfc28ece79aef41447d27a463ddd8662939fa3378"),
    "linux-arm64": Release("linux-arm64", "63a1e858a1a407c44ceb407ad133909b8cddedd713aea3b56d7ccb6db784eb48"),
    "windows-x86_64": Release("windows-x86_64", "e8be645de41d53d46c56b5baea67bd22b374703c7c9ef50a5bd3134ecc2d97d8"),
    "windows-arm64": Release("windows-arm64", "8c459fb1f3508c3256c62c09b2cc2d5be000431ed7b4e386d151127bd186cbd7"),
}


def host_release() -> Release | None:
    system, machine = platform.system().lower(), platform.machine().lower()
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if system == "darwin" and arch:
        major = platform.mac_ver()[0].split(".")[0]
        return _RELEASES["darwin-universal"] if major.isdigit() and int(major) >= 14 else None
    return _RELEASES.get(f"{system}-{arch}")


class DriverSetup(TypedDict):
    schema: Literal[1]
    version: str
    platform: str
    machine: str
    supported: bool
    installed: bool
    managed: bool
    mode: Literal["observe", "control", "custom", "off"]
    permission_app: Literal["CuaDriver", "nanobot Computer Use"]


class DriverCheck(TypedDict):
    connected: bool
    accessibility: bool | None
    screen_recording: bool | None
    capture_verified: bool
    sharing_paused: NotRequired[bool]


class CuaDriver:
    def __init__(self, config_path: Path):
        self.config_path = config_path.resolve()
        self.release = host_release()
        if platform.system() == "Darwin":
            from nanobot.apps.computer_use_native import package_digest

            try:
                digest = package_digest(self._inside(self.root))
            except (ValueError, OSError) as exc:
                raise DriverError("The local Computer Use package manifest is invalid. Restage the verified build.") from exc
            if digest:
                version = tuple(int(part) for part in platform.mac_ver()[0].split(".")[:2])
                self.release = Release("darwin-native", digest, native=True) if version >= (14, 2) else None

    @property
    def root(self) -> Path:
        return self._inside(self.config_path.parent / "apps" / NAME)

    @property
    def native(self) -> bool:
        return bool(self.release and self.release.native)

    @property
    def bundle(self) -> Path:
        return self.directory / ("nanobot Computer Use.app" if self.native else "CuaDriver.app")

    def _inside(self, path: Path) -> Path:
        # Do not follow redirected managed directories outside this instance.
        if not path.resolve().is_relative_to(self.config_path.parent):
            raise DriverError("Cua Driver's managed directory points outside this gateway's data directory.")
        return path

    def _release(self) -> Release:
        if self.release is None:
            raise DriverError("This gateway needs macOS 14+, Windows x64/ARM64, or Linux x64/ARM64 with a desktop session.")
        return self.release

    @property
    def directory(self) -> Path:
        return self._inside(self.root / self._release().directory)

    @property
    def executable(self) -> Path:
        return self._inside(self.directory / self._release().executable)

    def installed(self) -> bool:
        return bool(self.release and self.executable.is_file() and
                    (self.directory / ".nanobot-verified").is_file() and
                    (self.directory / ".nanobot-verified").read_text() == self.release.digest)

    def owns(self, config: MCPServerConfig) -> bool:
        return config.command == sys.executable and config.args == self._launch_args()

    def info(self, config: MCPServerConfig | None) -> DriverSetup:
        managed = config is None or self.owns(config)
        mode: Literal["observe", "control", "custom", "off"] = "off"
        if config:
            mode = "observe" if config.enabled_tools == OBSERVE_TOOLS else (
                "control" if config.enabled_tools == CONTROL_TOOLS else "custom")
        return {
            "schema": 1, "version": "0.1.0" if self.native else VERSION, "platform": platform.system(),
            "machine": platform.node(), "supported": self.release is not None,
            "installed": self.installed(), "managed": managed, "mode": mode,
            "permission_app": "nanobot Computer Use" if self.native else "CuaDriver",
        }

    def _launch_args(self) -> list[str]:
        return ["-m", "nanobot.apps.cua_driver_stdio", str(self.config_path)]

    def configuration(self, mode: str) -> MCPServerConfig:
        if mode not in {"observe", "control"}:
            raise DriverError("Choose observation or control access.", status=400)
        if not self.installed():
            raise DriverError("Install the verified Cua Driver package on this gateway first.")
        return MCPServerConfig(
            type="stdio", command=sys.executable, args=self._launch_args(),
            env={**DRIVER_ENV, **({"NANOBOT_COMPUTER_USE_NATIVE": "1"} if self.native else {})},
            tool_timeout=60, image_output="inline", retry_tool_calls=False,
            enabled_tools=list(OBSERVE_TOOLS if mode == "observe" else CONTROL_TOOLS),
        )

    async def install(self) -> None:
        """Download, verify and atomically publish; never launch the payload."""
        release = self._release()
        self._inside(self.root).mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = FileLock(str(self.root / "install.lock"))
        try:
            lock.acquire(timeout=0)
        except Timeout as exc:
            raise DriverError("Cua Driver is already being installed on this gateway. Refresh after it finishes.") from exc
        try:
            if self.installed():
                return
            if self.directory.exists():
                raise DriverError("The target Cua Driver directory already exists but is not verified. It has not been overwritten.")
            with tempfile.TemporaryDirectory(prefix="install-", dir=self.root) as temporary:
                staging = Path(temporary)
                archive = staging / release.filename
                async with asyncio.timeout(600):
                    if self.native:
                        source = self._inside(self.root / "native-package.tar.gz")
                        with source.open("rb") as stream:
                            digest = hashlib.file_digest(stream, "sha256").hexdigest()
                        if digest != release.digest:
                            raise DriverError("The staged native package checksum failed. Nothing was installed.", 502)
                        copying = asyncio.create_task(asyncio.to_thread(shutil.copyfile, source, archive))
                        try:
                            await asyncio.shield(copying)
                        except asyncio.CancelledError:
                            await copying
                            raise
                    else:
                        await _download(release, archive)
                unpack = asyncio.create_task(asyncio.to_thread(_unpack, archive, staging / "unpacked"))
                try:
                    await asyncio.shield(unpack)
                except asyncio.CancelledError:
                    # A worker must finish before TemporaryDirectory removes
                    # its destination; cancellation never leaves a writing worker.
                    await unpack
                    raise
                package = staging / "unpacked" / release.directory
                binary = package / release.executable
                if not binary.is_file() or not binary.resolve().is_relative_to(package):
                    raise DriverError("The verified archive does not contain the expected driver executable.", 502)
                # Keep the release's original copyright/license notices beside
                # the binary. A future package must not silently discard them.
                for notice in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
                    if not (package / notice).is_file() or not (package / notice).stat().st_size:
                        raise DriverError("The driver package is missing its license notices. Nothing was installed.", 502)
                if os.name != "nt":
                    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
                if release.target.startswith("darwin-"):
                    # Preserve Apple's signature; never remove quarantine or re-sign.
                    process = await asyncio.create_subprocess_exec(
                        "/usr/bin/codesign", "--verify", "--deep", "--strict", str(package / self.bundle.name),
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                    )
                    try:
                        returncode = await asyncio.wait_for(process.wait(), timeout=30)
                    except (TimeoutError, asyncio.CancelledError):
                        process.kill()
                        await process.wait()
                        raise
                    if returncode != 0:
                        raise DriverError("Apple's signature verification failed. The driver was not installed.", 502)
                (package / ".nanobot-verified").write_text(release.digest)
                package.rename(self.directory)
        except (httpx.HTTPError, TimeoutError) as exc:
            raise DriverError("Cua Driver download failed or timed out. Check this gateway's network and retry.", 502) from exc
        finally:
            lock.release()

    async def check(self) -> DriverCheck:
        """Connect and inspect grants without capturing desktop content or prompting."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        cfg = self.configuration("observe")
        result: DriverCheck = {
            "connected": False, "accessibility": None, "screen_recording": None, "capture_verified": False,
        }
        if platform.system() == "Darwin":
            from nanobot.apps.cua_driver_stdio import daemon_listening, endpoint

            # The signed app can be waiting at its first-run permissions gate.
            # Absence is not evidence that either grant was denied.
            if not daemon_listening(endpoint(self.config_path)):
                if self.native:
                    result["sharing_paused"] = endpoint(self.config_path).with_suffix(".paused").exists()
                return result
            if self.native:
                from nanobot.apps.computer_use_native import admin

                try:
                    native = await admin(endpoint(self.config_path), "status")
                except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
                    raise DriverError("Computer Use did not respond. Reconnect from Apps and try again.") from exc
                if native.get("protocol") != 1 or native.get("permission_app") != "nanobot Computer Use":
                    raise DriverError("The native host did not report the expected identity.")
                for key in ("connected", "accessibility", "screen_recording"):
                    if type(native.get(key)) is not bool:
                        raise DriverError("The native host returned an invalid permission status.")
                return {
                    "connected": native["connected"], "accessibility": native["accessibility"],
                    "screen_recording": native["screen_recording"], "capture_verified": False,
                    "sharing_paused": native.get("sharing_paused") is True,
                }
        # A check never auto-launches a macOS app or substitutes the terminal's grants.
        args = [*cfg.args, "--check"]
        try:
            async with asyncio.timeout(25):
                async with stdio_client(StdioServerParameters(command=cfg.command, args=args, env=cfg.env)) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        available = await session.list_tools()
                        names = {tool.name for tool in available.tools}
                        if not set(OBSERVE_TOOLS).issubset(names):
                            raise DriverError("The driver is missing the expected observation tools.")
                        result["connected"] = True
                        if platform.system() == "Darwin":
                            permissions = await session.call_tool("check_permissions", {
                                "prompt": False, "probe_direct_capture": False,
                            })
                            data = permissions.structuredContent or {}
                            source = data.get("source")
                            if not permissions.isError and isinstance(source, dict) and cast(dict[str, object], source).get("attribution") == "driver-daemon":
                                for key in ("accessibility", "screen_recording"):
                                    if type(data.get(key)) is bool:
                                        result[key] = data[key]
            return result
        except DriverError:
            raise
        except Exception as exc:
            raise DriverError("The driver could not be checked. Enable it, finish system permissions on the gateway computer, and retry.") from exc

    async def open_setup(self, target: str) -> None:
        """Reveal only this installed bundle or a fixed macOS permission pane.

        These user-invoked settings actions neither grant TCC access nor launch
        the driver. They are never exposed as agent tools.
        """
        if platform.system() != "Darwin" or not self.installed():
            raise DriverError("Install Cua Driver on a macOS gateway before opening system setup.")
        panes = {
            "accessibility": "Privacy_Accessibility",
            "screen_recording": "Privacy_ScreenCapture",
        }
        if target == "finder":
            args = ["-R", str(self._inside(self.bundle))]
        elif target in panes:
            if self.native:
                from nanobot.apps.computer_use_native import admin
                from nanobot.apps.cua_driver_stdio import ensure_daemon

                address = await asyncio.to_thread(ensure_daemon, self)
                result = await admin(address, "request_permission", target)
                if result.get("prompted") is True:
                    return  # Finish this system prompt before opening a pane.
            args = [f"x-apple.systempreferences:com.apple.preference.security?{panes[target]}"]
        else:
            raise DriverError("Choose Accessibility, Screen Recording, or Finder.", 400)
        await self._open(args)

    async def request_permissions(self) -> None:
        """Start or reuse the signed daemon's own first-run permission flow."""
        if platform.system() != "Darwin" or not self.installed():
            raise DriverError("Install Cua Driver on a macOS gateway before requesting system permissions.")
        from nanobot.apps.cua_driver_stdio import ensure_daemon

        starting = asyncio.create_task(asyncio.to_thread(ensure_daemon, self))
        try:
            # Only wait for its socket, not for the user to approve access.
            # Repeated setup requests and MCP reload share its lifecycle lock.
            await asyncio.shield(starting)
            if self.native:
                from nanobot.apps.computer_use_native import admin
                from nanobot.apps.cua_driver_stdio import endpoint

                await admin(endpoint(self.config_path), "request_permission", "accessibility")
        except asyncio.CancelledError:
            await starting
            raise
        except (Timeout, subprocess.SubprocessError, OSError) as exc:
            raise DriverError("System setup could not start. Check Cua Driver on the gateway computer.") from exc

    @staticmethod
    async def _open(args: list[str]) -> None:
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/open", *args,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            code = await asyncio.wait_for(process.wait(), timeout=10)
        except (TimeoutError, asyncio.CancelledError) as exc:
            process.kill()
            await process.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise DriverError("System setup did not open. Open System Settings on the gateway computer.") from None
        if code != 0:
            raise DriverError("System setup could not open. Use the signed-in desktop on the gateway computer.")

    async def stop(self) -> None:
        if platform.system() != "Darwin" or not self.installed():
            return
        from nanobot.apps.cua_driver_stdio import stop_daemon

        stopping = asyncio.create_task(asyncio.to_thread(stop_daemon, self))
        try:
            await asyncio.shield(stopping)
        except asyncio.CancelledError:
            await stopping
            raise
        except Timeout as exc:
            raise DriverError("The driver is still starting or stopping. Try again shortly.") from exc

    async def uninstall(self, *, reset_permissions: bool = False) -> None:
        """Remove only this instance's verified package after access is disabled.

        Only the independent native app supports explicitly resetting its two
        desktop grants. Never reset the shared upstream CuaDriver identity.
        A failed stop or reset leaves the package available for recovery.
        """
        from nanobot.config.loader import load_config

        if load_config(self.config_path).tools.mcp_servers.get(NAME) is not None:
            raise DriverError("Disable Computer Use before uninstalling its driver.")
        if reset_permissions and not self.native:
            raise DriverError("Only the independent nanobot Computer Use app can reset its Mac permissions.")
        if not self.release:
            return
        self._inside(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(self.root / "install.lock"))
        try:
            lock.acquire(timeout=0)
        except Timeout as exc:
            raise DriverError("Computer Use is being installed or removed. Wait for it to finish.") from exc
        try:
            if not self.directory.exists():
                if reset_permissions:
                    raise DriverError("The native app is not installed. Manage any remaining grants in System Settings.")
                return
            if not self.installed() or self.directory.is_symlink():
                raise DriverError("The driver directory is not a verified managed installation. No files were removed.")
            await self.stop()
            if reset_permissions:
                await self._reset_native_permissions()
            removal = asyncio.create_task(asyncio.to_thread(shutil.rmtree, self.directory))
            try:
                await asyncio.shield(removal)
            except asyncio.CancelledError:
                await removal
                raise
        except OSError as exc:
            raise DriverError("Computer Use is disabled, but its package could not be removed. Check file access and retry.") from exc
        finally:
            lock.release()

    async def _reset_native_permissions(self) -> None:
        # Fixed services and identity: settings callers cannot choose an app,
        # reset other apps, or grant access. Run before removing the app bundle.
        # A just-installed app may never have been launched. tccutil requires
        # its identity in Launch Services; registering the exact bundle is inert.
        operations = [
            ("app registration", [
                "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister",
                "-f", str(self.bundle),
            ]),
            *[(service, ["/usr/bin/tccutil", "reset", service, "io.nanobot.computer-use"])
              for service in ("Accessibility", "ScreenCapture")],
        ]
        for service, command in operations:
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    returncode = await asyncio.wait_for(process.wait(), timeout=15)
                except (TimeoutError, asyncio.CancelledError):
                    process.kill()
                    await process.wait()
                    raise
                if returncode:
                    raise OSError("macOS refused the permission reset")
            except (OSError, TimeoutError) as exc:
                raise DriverError(
                    f"Computer Use is disabled, but macOS could not reset {service}. "
                    "Some grants may already be reset. The app was kept; retry uninstalling "
                    "or revoke its permissions in System Settings."
                ) from exc


async def _download(release: Release, destination: Path) -> None:
    digest = hashlib.sha256()
    received = 0
    async with httpx.AsyncClient(
        transport=PinnedDNSAsyncTransport(), follow_redirects=True, max_redirects=5,
        timeout=httpx.Timeout(60, connect=20),
    ) as client:
        async with client.stream("GET", _BASE_URL + release.filename) as response:
            response.raise_for_status()
            with destination.open("xb") as output:
                async for chunk in response.aiter_bytes():
                    received += len(chunk)
                    if received > _MAX_DOWNLOAD:
                        raise DriverError("Cua Driver download exceeds the supported package size.", 413)
                    digest.update(chunk)
                    output.write(chunk)
    if digest.hexdigest() != release.digest:
        raise DriverError("Cua Driver checksum verification failed. Nothing was installed; retry the download.", 502)


def _unpack(archive: Path, destination: Path) -> None:
    destination.mkdir()

    def safe_name(name: str) -> None:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
            raise DriverError("The driver archive contains an unsafe path.", 502)

    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            if len(members) > 20_000 or sum(member.file_size for member in members) > _MAX_UNPACKED:
                raise DriverError("The driver archive is too large to unpack.", 413)
            for member in members:
                safe_name(member.filename)
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise DriverError("The driver zip contains an unsupported symbolic link.", 502)
            bundle.extractall(destination)
    else:
        with tarfile.open(archive) as bundle:
            members = bundle.getmembers()
            if len(members) > 20_000 or sum(member.size for member in members) > _MAX_UNPACKED:
                raise DriverError("The driver archive is too large to unpack.", 413)
            for member in members:
                safe_name(member.name)
            try:
                bundle.extractall(destination, members=members, filter="data")
            except (tarfile.FilterError, OSError) as exc:
                raise DriverError("The driver archive could not be safely unpacked.", 502) from exc
