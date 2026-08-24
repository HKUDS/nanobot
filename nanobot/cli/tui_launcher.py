"""Launch the TypeScript terminal client against the local gateway."""

from __future__ import annotations

import hashlib
import io
import os
import platform
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from nanobot import __version__
from nanobot.cli.process_identity import named_executable
from nanobot.cli.runtime_config import _model_display
from nanobot.cli.webui_support import (
    _gateway_health_ready,
    _gateway_instance_command,
    _host_for_local_browser,
    _webui_endpoint_reachable,
)
from nanobot.config.paths import get_data_dir
from nanobot.config.schema import Config

if TYPE_CHECKING:
    from nanobot.gateway import GatewayClientLease


class TuiUnavailableError(RuntimeError):
    """Raised when the native TypeScript TUI cannot run on this installation."""


class TuiSessionError(ValueError):
    """Raised when a session selector cannot be opened by the native TUI."""


_TUI_RELEASE_FILES = (
    "THIRD_PARTY_NOTICES.txt",
    "RELINKING.md",
    "SOURCE_OFFER.md",
    "LICENSE",
    "BUN-1.3.13-LICENSE.md",
    "LGPL-2.0.txt",
    "LGPL-2.1.txt",
    "nanobot-tui-source.tar.gz",
)
_TUI_RELEASE_LIMITS = {
    "THIRD_PARTY_NOTICES.txt": 4 * 1024 * 1024,
    "RELINKING.md": 256 * 1024,
    "SOURCE_OFFER.md": 256 * 1024,
    "LICENSE": 256 * 1024,
    "BUN-1.3.13-LICENSE.md": 1024 * 1024,
    "LGPL-2.0.txt": 256 * 1024,
    "LGPL-2.1.txt": 256 * 1024,
    "nanobot-tui-source.tar.gz": 20 * 1024 * 1024,
    "MANIFEST.sha256": 64 * 1024,
}
# Keep in sync with TUI_DETACH_EXIT_CODE in tui/src/index.ts.
_TUI_DETACH_EXIT_CODE = 90


@dataclass(frozen=True)
class _GatewayHandle:
    base_url: str
    lease: GatewayClientLease | None = None


def launch_tui(
    config: Config,
    *,
    config_path: Path,
    workspace_override: str | None,
    session_id: str | None,
    theme: str,
    initial_view: Literal["config"] | None = None,
) -> int:
    """Run the native TUI against the shared local gateway."""
    chat_id = _initial_tui_chat_id(session_id)
    tui_workspace = _initial_tui_workspace(workspace_override)
    command = _resolve_tui_command()
    base_url, bootstrap_secret = _tui_gateway_connection(config)
    gateway: _GatewayHandle | None = None
    process: subprocess.Popen[Any] | None = None
    try:
        env = os.environ.copy()
        env.pop("NANOBOT_TUI_WS_URL", None)
        env.pop("NANOBOT_TUI_API_TOKEN", None)
        env.pop("NANOBOT_TUI_OPEN", None)
        env.update(
            {
                "NANOBOT_TUI_BOOTSTRAP_URL": f"{base_url}/webui/bootstrap",
                "NANOBOT_TUI_API_URL": base_url,
                "NANOBOT_TUI_MODEL": _model_display(config)[0],
                "NANOBOT_TUI_MODEL_PRESET": config.agents.defaults.model_preset or "default",
                "NANOBOT_TUI_WORKSPACE": str(tui_workspace),
                "NANOBOT_TUI_VERSION": __version__,
                "NANOBOT_TUI_ACCESS": (
                    "workspace access" if config.tools.restrict_to_workspace else "full access"
                ),
                "NANOBOT_TUI_THEME": theme,
                "NANOBOT_TUI_GATEWAY_STOP_COMMAND": _gateway_instance_command(
                    "stop",
                    config_path=config_path,
                    workspace=workspace_override,
                ),
            }
        )
        if bootstrap_secret:
            env["NANOBOT_TUI_BOOTSTRAP_SECRET"] = bootstrap_secret
        else:
            env.pop("NANOBOT_TUI_BOOTSTRAP_SECRET", None)
        if chat_id:
            env["NANOBOT_TUI_CHAT_ID"] = chat_id
        else:
            env.pop("NANOBOT_TUI_CHAT_ID", None)
        if initial_view:
            env["NANOBOT_TUI_OPEN"] = initial_view
        try:
            process = subprocess.Popen(command, env=env)
        except OSError as exc:
            raise TuiUnavailableError(f"could not start the native TUI: {exc}") from exc
        gateway = _ensure_gateway(
            config,
            config_path=config_path,
            workspace_override=workspace_override,
            wait_until_ready=False,
        )
        exit_code = process.wait()
        if exit_code == _TUI_DETACH_EXIT_CODE:
            lease = gateway.lease
            if lease is not None:
                lease.mark_persistent()
            return 0
        return exit_code
    except BaseException:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        raise
    finally:
        lease = getattr(gateway, "lease", None) if gateway is not None else None
        if lease is not None:
            # Returning to the shell must not wait for process termination. The
            # gateway's client monitor observes the released last lease and owns
            # the orderly on-demand shutdown.
            lease.release(wait_for_stop=False)


def _resolve_tui_command() -> list[str]:
    override = os.environ.get("NANOBOT_TUI_BIN", "").strip()
    if override:
        executable = Path(override).expanduser().resolve(strict=False)
        if not executable.is_file():
            raise TuiUnavailableError(f"NANOBOT_TUI_BIN does not exist: {executable}")
        return [str(executable)]

    suffix = ".exe" if os.name == "nt" else ""
    system = {"Windows": "win32", "Darwin": "darwin", "Linux": "linux"}.get(
        platform.system(),
        platform.system().lower(),
    )
    machine = {"x86_64": "x64", "AMD64": "x64", "aarch64": "arm64"}.get(
        platform.machine(),
        platform.machine().lower(),
    )
    if system == "win32" and machine == "arm64":
        raise TuiUnavailableError(
            "the native TUI is not available on Windows ARM64 because Bun FFI is disabled "
            "on that platform; use the classic prompt until the upstream runtime supports it"
        )
    asset = f"nanobot-tui-{system}-{machine}{suffix}"
    source_dir = _source_checkout_tui_dir()
    if source_dir is not None:
        bun = shutil.which("bun")
        if not bun:
            raise TuiUnavailableError(
                "this source checkout requires Bun to run its matching TUI; "
                "install Bun, then run `nanobot agent` again"
            )
        return _resolve_source_tui_command(source_dir, bun)

    packaged = Path(__file__).resolve().parents[1] / "tui" / "bin" / asset
    if packaged.is_file():
        return [str(packaged)]

    downloaded = _download_release_tui(asset)
    if downloaded is not None:
        return [str(downloaded)]

    raise TuiUnavailableError(
        f"no native TUI archive is published for nanobot {__version__} on this platform; "
        "current source installs must be editable and keep their checkout and Bun available, "
        "while released packages need a matching GitHub release archive; use "
        "`nanobot agent --classic` if intentional"
    )


def _source_checkout_tui_dir() -> Path | None:
    """Return this checkout's TUI source, never a neighboring unrelated directory."""
    return _tui_source_dir(Path(__file__).resolve().parents[2])


def _tui_source_dir(project_root: Path) -> Path | None:
    project_root = project_root.resolve(strict=False)
    source_dir = project_root / "tui"
    if (project_root / "pyproject.toml").is_file() and (source_dir / "package.json").is_file():
        return source_dir
    return None


def _resolve_source_tui_command(source_dir: Path, bun: str) -> list[str]:
    dependency = source_dir / "node_modules" / "@opentui" / "core"
    try:
        install = subprocess.run(
            [bun, "install", "--frozen-lockfile"],
            cwd=source_dir,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise TuiUnavailableError(f"could not install TUI dependencies: {exc}") from exc
    if install.returncode != 0 or not dependency.is_dir():
        detail = (install.stderr or install.stdout).strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise TuiUnavailableError(f"could not install TUI dependencies{suffix}")
    executable = named_executable(
        bun,
        name="nanobot-tui",
        directory=get_data_dir() / "run" / "executables",
    )
    return [executable, str(source_dir / "src" / "index.ts")]


def _download_release_tui(asset: str) -> Path | None:
    """Install the complete, version-matched TUI release bundle."""
    if os.environ.get("NANOBOT_TUI_NO_DOWNLOAD") == "1":
        return None
    version = __version__.strip()
    if not version or version.endswith((".dev0", "+dev")):
        return None

    target_dir = get_data_dir() / "bin" / "tui" / version
    cached = _cached_release_tui(target_dir, asset)
    if cached is not None:
        return cached

    base = f"https://github.com/HKUDS/nanobot/releases/download/v{version}"
    archive_name = f"{asset}.zip"
    try:
        checksum = _read_release_asset(f"{base}/{archive_name}.sha256", max_bytes=1024)
        expected = _release_checksum(checksum, archive_name)
        if expected is None:
            return None
        archive = _read_release_asset(f"{base}/{archive_name}", max_bytes=200 * 1024 * 1024)
    except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError):
        return None
    if hashlib.sha256(archive).hexdigest() != expected:
        raise TuiUnavailableError("downloaded TUI archive failed checksum verification")
    files = _verified_release_archive(archive, asset)

    temporary: dict[str, Path] = {}
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            path = target_dir / name
            pending = path.with_name(f"{path.name}.tmp-{os.getpid()}")
            pending.write_bytes(content)
            if name == asset and os.name != "nt":
                pending.chmod(0o755)
            temporary[name] = pending
        for name in _release_bundle_names(asset):
            temporary[name].replace(target_dir / name)
    except OSError:
        for path in temporary.values():
            path.unlink(missing_ok=True)
        _clear_cached_release(target_dir, asset)
        return None
    return target_dir / asset


def _release_bundle_names(asset: str) -> tuple[str, ...]:
    return (asset, *_TUI_RELEASE_FILES, "MANIFEST.sha256")


def _release_checksum(raw: bytes, archive_name: str) -> str | None:
    try:
        parts = raw.decode("utf-8").split()
    except UnicodeDecodeError:
        return None
    if len(parts) != 2 or parts[1] != archive_name:
        return None
    digest = parts[0].lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        return None
    return digest


def _release_manifest(raw: bytes, asset: str) -> dict[str, str]:
    expected_names = set(_release_bundle_names(asset)[:-1])
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise TuiUnavailableError("TUI release manifest is not valid UTF-8") from exc
    checksums: dict[str, str] = {}
    for line in lines:
        digest, separator, name = line.partition("  ")
        digest = digest.lower()
        if (
            separator != "  "
            or name not in expected_names
            or name in checksums
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise TuiUnavailableError("TUI release manifest is malformed")
        checksums[name] = digest
    if set(checksums) != expected_names:
        raise TuiUnavailableError("TUI release manifest is incomplete")
    return checksums


def _verified_release_archive(raw: bytes, asset: str) -> dict[str, bytes]:
    expected_names = set(_release_bundle_names(asset))
    files: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries if not entry.is_dir()]
            if len(names) != len(entries) or len(names) != len(set(names)):
                raise TuiUnavailableError("TUI release archive contains invalid entries")
            if set(names) != expected_names:
                raise TuiUnavailableError("TUI release archive is incomplete")
            for entry in entries:
                limit = 150 * 1024 * 1024 if entry.filename == asset else _TUI_RELEASE_LIMITS[
                    entry.filename
                ]
                if entry.file_size == 0 or entry.file_size > limit:
                    raise TuiUnavailableError(
                        f"TUI release file has an invalid size: {entry.filename}"
                    )
                files[entry.filename] = archive.read(entry)
    except zipfile.BadZipFile as exc:
        raise TuiUnavailableError("downloaded TUI archive is not a valid ZIP file") from exc

    checksums = _release_manifest(files["MANIFEST.sha256"], asset)
    for name, expected in checksums.items():
        if hashlib.sha256(files[name]).hexdigest() != expected:
            raise TuiUnavailableError(f"TUI release file failed verification: {name}")
    return files


def _cached_release_tui(target_dir: Path, asset: str) -> Path | None:
    target = target_dir / asset
    manifest = target_dir / "MANIFEST.sha256"
    if not target.is_file() and not manifest.exists():
        return None
    try:
        checksums = _release_manifest(manifest.read_bytes(), asset)
        for name, expected in checksums.items():
            if hashlib.sha256((target_dir / name).read_bytes()).hexdigest() != expected:
                raise OSError("cached release checksum mismatch")
        if os.name != "nt":
            target.chmod(0o755)
    except (OSError, TuiUnavailableError):
        _clear_cached_release(target_dir, asset)
        return None
    return target


def _clear_cached_release(target_dir: Path, asset: str) -> None:
    for name in _release_bundle_names(asset):
        try:
            (target_dir / name).unlink(missing_ok=True)
        except OSError:
            pass


def _read_release_asset(url: str, *, max_bytes: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"nanobot/{__version__}"})
    with urllib.request.urlopen(request, timeout=5) as response:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise OSError("release asset exceeds size limit")
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise OSError("release asset exceeds size limit")
    return body


def _ensure_gateway(
    config: Config,
    *,
    config_path: Path,
    workspace_override: str | None,
    wait_until_ready: bool = True,
) -> _GatewayHandle:
    from nanobot.gateway import (
        GatewayClientLease,
        GatewayInstance,
        GatewayRuntime,
    )

    base_url, _bootstrap_secret = _tui_gateway_connection(config)
    instance = GatewayInstance.resolve(
        config_path=config_path,
        workspace=workspace_override,
    )
    runtime = GatewayRuntime(paths=instance.paths)
    lease = GatewayClientLease(runtime, kind="tui")
    lease.acquire()
    try:
        status = runtime.status()
        endpoint_reachable = _webui_endpoint_reachable(base_url)
        if status.running:
            if status.port not in {None, config.gateway.port}:
                raise TuiUnavailableError(
                    "the matching gateway instance is running on a different port; "
                    "restart it or use `nanobot agent --classic`"
                )
            if endpoint_reachable or not wait_until_ready:
                return _GatewayHandle(base_url=base_url, lease=lease)
        elif endpoint_reachable:
            raise TuiUnavailableError(
                "the configured gateway port belongs to a different nanobot instance; "
                "stop that instance or use `nanobot agent --classic`"
            )

        result = lease.ensure_on_demand_gateway(
            instance.start_options(port=config.gateway.port)
        )
        if not result.ok and result.message != "gateway_already_running":
            raise TuiUnavailableError(
                f"could not start the local gateway ({result.message}); "
                f"logs: {result.status.log_path}"
            )

        if not wait_until_ready:
            return _GatewayHandle(base_url=base_url, lease=lease)

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if _webui_endpoint_reachable(base_url):
                current = runtime.status()
                if current.running and current.port in {None, config.gateway.port}:
                    return _GatewayHandle(base_url=base_url, lease=lease)
                break
            if not runtime.status().running and not _gateway_health_ready(
                config.gateway.host,
                config.gateway.port,
            ):
                break
            time.sleep(0.1)

        raise TuiUnavailableError(
            f"local gateway did not become ready; logs: {result.status.log_path}"
        )
    except BaseException:
        lease.release(timeout_s=5)
        raise


def _tui_gateway_connection(config: Config) -> tuple[str, str]:
    """Read the small bootstrap subset without importing the WebSocket runtime."""
    raw: object = getattr(config.channels, "websocket", None)
    settings = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
    host = _host_for_local_browser(str(settings.get("host") or "127.0.0.1"))
    try:
        port = int(settings.get("port") or 8765)
    except (TypeError, ValueError):
        port = 8765
    secret = str(
        settings.get("tokenIssueSecret")
        or settings.get("token_issue_secret")
        or settings.get("token")
        or ""
    ).strip()
    return f"http://{host}:{port}", secret


def _websocket_chat_id(session_id: str) -> str | None:
    """Map the CLI selector to the WebSocket namespace used by the native TUI."""
    if session_id.startswith("websocket:"):
        return session_id.split(":", 1)[1] or None
    if ":" in session_id:
        raise TuiSessionError(
            "the native TUI can open only WebSocket sessions; use --classic to resume "
            f"{session_id!r}"
        )
    return session_id or None


def _initial_tui_chat_id(session_id: str | None) -> str | None:
    """Start fresh unless the caller explicitly selects a TUI chat."""
    if session_id is not None:
        return _websocket_chat_id(session_id)
    return None


def _initial_tui_workspace(workspace_override: str | None) -> Path:
    """Use the launch directory unless the caller explicitly selects a workspace."""
    workspace = Path(workspace_override) if workspace_override is not None else Path.cwd()
    return workspace.expanduser().resolve(strict=False)
