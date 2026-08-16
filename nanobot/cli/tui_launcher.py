"""Launch the TypeScript terminal client against the local gateway."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from nanobot import __version__
from nanobot.cli.runtime_config import _model_display
from nanobot.cli.webui_support import (
    _gateway_health_ready,
    _webui_browser_url,
    _webui_endpoint_reachable,
    webui_bootstrap_secret,
)
from nanobot.config.paths import get_data_dir, is_default_workspace
from nanobot.config.schema import Config


class TuiUnavailableError(RuntimeError):
    """Raised when the native TypeScript TUI cannot run on this installation."""


@dataclass(frozen=True)
class _GatewayHandle:
    base_url: str


def launch_tui(
    config: Config,
    *,
    config_path: Path,
    workspace_override: str | None,
    session_id: str | None,
    theme: str,
) -> int:
    """Run the native TUI against the shared local gateway."""
    command = _resolve_tui_command()
    gateway = _ensure_gateway(
        config,
        config_path=config_path,
        workspace_override=workspace_override,
    )
    bootstrap = _fetch_bootstrap(
        gateway.base_url,
        secret=webui_bootstrap_secret(config),
    )
    env = os.environ.copy()
    env.update(
        {
            "NANOBOT_TUI_WS_URL": _authenticated_ws_url(bootstrap),
            "NANOBOT_TUI_API_URL": gateway.base_url,
            "NANOBOT_TUI_API_TOKEN": str(bootstrap.get("api_token") or ""),
            "NANOBOT_TUI_MODEL": _model_display(config)[0],
            "NANOBOT_TUI_MODEL_PRESET": config.agents.defaults.model_preset or "default",
            "NANOBOT_TUI_WORKSPACE": str(config.workspace_path),
            "NANOBOT_TUI_VERSION": __version__,
            "NANOBOT_TUI_ACCESS": (
                "workspace access" if config.tools.restrict_to_workspace else "full access"
            ),
            "NANOBOT_TUI_THEME": theme,
        }
    )
    state_path = config_path.parent / "tui" / "state.json"
    env["NANOBOT_TUI_STATE_PATH"] = str(state_path)
    chat_id = _initial_tui_chat_id(session_id, state_path)
    if chat_id:
        env["NANOBOT_TUI_CHAT_ID"] = chat_id
    else:
        env.pop("NANOBOT_TUI_CHAT_ID", None)
    try:
        return subprocess.run(command, env=env, check=False).returncode
    except OSError as exc:
        raise TuiUnavailableError(f"could not start the native TUI: {exc}") from exc


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
    packaged = Path(__file__).resolve().parents[1] / "tui" / "bin" / asset
    if packaged.is_file():
        return [str(packaged)]

    source_dir = Path(__file__).resolve().parents[2] / "tui"
    bun = shutil.which("bun")
    if bun and (source_dir / "package.json").is_file():
        return _resolve_source_tui_command(source_dir, bun)

    downloaded = _download_release_tui(asset)
    if downloaded is not None:
        return [str(downloaded)]

    raise TuiUnavailableError(
        "this build does not include the native TUI; install Bun for a source checkout "
        "or use `nanobot agent --classic`"
    )


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
    return [bun, str(source_dir / "src" / "index.ts")]


def _download_release_tui(asset: str) -> Path | None:
    """Install the version-matched release sidecar into nanobot's data directory."""
    if os.environ.get("NANOBOT_TUI_NO_DOWNLOAD") == "1":
        return None
    version = __version__.strip()
    if not version or version.endswith((".dev0", "+dev")):
        return None

    target_dir = get_data_dir() / "bin" / "tui" / version
    target = target_dir / asset
    cached_checksum = target.with_name(f"{target.name}.sha256")
    if target.is_file():
        try:
            expected = cached_checksum.read_text(encoding="utf-8").split()[0].lower()
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
        except (OSError, IndexError):
            expected = ""
            actual = ""
        if len(expected) == 64 and actual == expected:
            if os.name != "nt":
                try:
                    target.chmod(0o755)
                except OSError:
                    return None
            return target
        try:
            target.unlink(missing_ok=True)
            cached_checksum.unlink(missing_ok=True)
        except OSError:
            return None

    base = f"https://github.com/HKUDS/nanobot/releases/download/v{version}"
    try:
        checksum = _read_release_asset(f"{base}/{asset}.sha256", max_bytes=1024).decode()
        expected = checksum.split()[0].lower()
        if len(expected) != 64:
            return None
        binary = _read_release_asset(f"{base}/{asset}", max_bytes=150 * 1024 * 1024)
    except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError):
        return None
    if hashlib.sha256(binary).hexdigest() != expected:
        raise TuiUnavailableError("downloaded TUI binary failed checksum verification")

    temporary = target.with_suffix(f"{target.suffix}.tmp-{os.getpid()}")
    temporary_checksum = cached_checksum.with_suffix(
        f"{cached_checksum.suffix}.tmp-{os.getpid()}"
    )
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(binary)
        temporary_checksum.write_text(f"{expected}  {asset}\n", encoding="utf-8")
        if os.name != "nt":
            temporary.chmod(0o755)
        temporary.replace(target)
        temporary_checksum.replace(cached_checksum)
    except OSError:
        temporary.unlink(missing_ok=True)
        temporary_checksum.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        cached_checksum.unlink(missing_ok=True)
        return None
    return target


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
) -> _GatewayHandle:
    from nanobot.gateway import GatewayRuntime, GatewayRuntimePaths, GatewayStartOptions

    base_url = _webui_browser_url(config).split("/#/", 1)[0].rstrip("/")
    workspace_override_path = (
        str(Path(workspace_override).expanduser().resolve(strict=False))
        if workspace_override
        else None
    )
    effective_workspace = config.workspace_path.resolve(strict=False)
    runtime_workspace = (
        None if is_default_workspace(effective_workspace) else str(effective_workspace)
    )
    runtime = GatewayRuntime(
        paths=GatewayRuntimePaths.for_instance(
            data_dir=config_path.parent,
            workspace=runtime_workspace,
            config_path=str(config_path),
        )
    )
    status = runtime.status()
    endpoint_reachable = _webui_endpoint_reachable(base_url)
    if status.running:
        if status.port not in {None, config.gateway.port}:
            raise TuiUnavailableError(
                "the matching gateway instance is running on a different port; "
                "restart it or use `nanobot agent --classic`"
            )
        if endpoint_reachable:
            return _GatewayHandle(base_url=base_url)
    elif endpoint_reachable:
        raise TuiUnavailableError(
            "the configured gateway port belongs to a different nanobot instance; "
            "stop that instance or use `nanobot agent --classic`"
        )

    result = runtime.start_background(
        GatewayStartOptions(
            port=config.gateway.port,
            workspace=workspace_override_path,
            config_path=str(config_path),
        )
    )
    started_here = result.ok
    if not result.ok and result.message != "gateway_already_running":
        raise TuiUnavailableError(
            f"could not start the local gateway ({result.message}); logs: {result.status.log_path}"
        )

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if _webui_endpoint_reachable(base_url):
            current = runtime.status()
            if current.running and current.port in {None, config.gateway.port}:
                return _GatewayHandle(base_url=base_url)
            break
        if not runtime.status().running and not _gateway_health_ready(
            config.gateway.host,
            config.gateway.port,
        ):
            break
        time.sleep(0.1)

    if started_here:
        runtime.stop(timeout_s=5)
    raise TuiUnavailableError(
        f"local gateway did not become ready; logs: {result.status.log_path}"
    )


def _fetch_bootstrap(base_url: str, *, secret: str) -> dict[str, Any]:
    headers = {"X-Nanobot-Auth": secret} if secret else {}
    request = urllib.request.Request(f"{base_url}/webui/bootstrap", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raw_payload: Any = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise TuiUnavailableError(
            f"could not authenticate with the local gateway: {exc}"
        ) from exc
    if not isinstance(raw_payload, dict):
        raise TuiUnavailableError("gateway bootstrap response is missing ws_path")
    payload = cast(dict[str, Any], raw_payload)
    if not payload.get("ws_path"):
        raise TuiUnavailableError("gateway bootstrap response is missing ws_path")
    return payload


def _authenticated_ws_url(bootstrap: dict[str, Any]) -> str:
    raw_url = str(bootstrap.get("ws_url") or "").strip()
    if not raw_url:
        raise TuiUnavailableError("gateway bootstrap response is missing ws_url")
    parsed = urllib.parse.urlsplit(raw_url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    token = str(bootstrap.get("token") or "").strip()
    if token:
        query.append(("token", token))
    query.append(("client_id", f"tui-{os.getpid()}"))
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
    )


def _websocket_chat_id(session_id: str) -> str | None:
    """Map the CLI selector to the WebSocket namespace used by the native TUI."""
    if session_id.startswith("websocket:"):
        return session_id.split(":", 1)[1] or None
    if ":" in session_id:
        raise TuiUnavailableError(
            "the native TUI can open only WebSocket sessions; use --classic to resume "
            f"{session_id!r}"
        )
    return session_id or None


def _initial_tui_chat_id(session_id: str | None, state_path: Path) -> str | None:
    """Resume the default TUI, while keeping an explicit selector authoritative."""
    if session_id is not None:
        return _websocket_chat_id(session_id)
    return _read_tui_chat_id(state_path) or "tui-direct"


def _read_tui_chat_id(path: Path) -> str | None:
    """Read the last attached chat without making launch depend on optional state."""
    try:
        raw_payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw_payload, dict):
        return None
    payload = cast(dict[str, Any], raw_payload)
    value = payload.get("chat_id")
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 256 or any(character in value for character in "\r\n"):
        return None
    return value
