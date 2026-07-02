"""Optional nanobot feature discovery and enablement."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any

from loguru import logger
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from nanobot.config.schema import Config


class OptionalFeatureError(Exception):
    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class InstallResult:
    ok: bool
    label: str
    pip_cmd: list[str]
    failed_cmd: list[str] | None = None
    output: str = ""


_INSTALL_TIMEOUT_SECONDS = 300
_DEFAULT_ENABLED_CHANNELS = frozenset({"websocket"})
_LOG_OUTPUT_LIMIT = 4000
_PACKAGE_INDEX_URLS = {
    "default": "",
    "pypi": "https://pypi.org/simple",
    "tuna": "https://pypi.tuna.tsinghua.edu.cn/simple",
    "aliyun": "https://mirrors.aliyun.com/pypi/simple",
    "ustc": "https://pypi.mirrors.ustc.edu.cn/simple",
    "douban": "https://pypi.doubanio.com/simple",
    "huawei": "https://repo.huaweicloud.com/repository/pypi/simple",
}


def load_pyproject(path: Path) -> dict[str, Any]:
    try:
        import tomllib

        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def optional_dependency_groups_from_metadata() -> dict[str, list[str] | None]:
    try:
        from importlib.metadata import metadata, requires
    except Exception:
        return {}

    try:
        extras = metadata("nanobot-ai").get_all("Provides-Extra") or []
        groups: dict[str, list[str] | None] = {name: [] for name in extras if name != "dev"}
        for raw in requires("nanobot-ai") or []:
            try:
                req = Requirement(raw)
            except Exception:
                continue
            if not req.marker:
                continue
            for extra, deps in groups.items():
                if deps is not None and req.marker.evaluate({"extra": extra}):
                    deps.append(raw)
        return groups
    except Exception:
        return {}


def optional_dependency_groups() -> dict[str, list[str] | None]:
    root = Path(__file__).resolve().parents[1]
    project = load_pyproject(root / "pyproject.toml").get("project", {})
    deps = project.get("optional-dependencies", {})
    if isinstance(deps, dict) and deps:
        return {
            name: list(values)
            for name, values in deps.items()
            if name != "dev" and isinstance(values, list)
        }
    return optional_dependency_groups_from_metadata()


def _install_requirements_for_extra(extra: str, deps: list[str]) -> list[str]:
    install_args: list[str] = []
    for raw in deps:
        try:
            req = Requirement(raw)
        except Exception:
            install_args.append(raw)
            continue
        if req.marker and not req.marker.evaluate({"extra": extra}):
            continue
        req.marker = None
        install_args.append(str(req))
    return install_args


def package_index_url(preset: str) -> str:
    key = (preset or "default").strip().lower()
    if key not in _PACKAGE_INDEX_URLS:
        available = ", ".join(sorted(_PACKAGE_INDEX_URLS))
        raise OptionalFeatureError(f"Unknown package index preset: {preset}. Available: {available}")
    return _PACKAGE_INDEX_URLS[key]


def install_args_for_extra(
    extra: str,
    deps: list[str] | None,
    *,
    package_index: str = "default",
) -> tuple[list[str], str]:
    index_url = package_index_url(package_index)
    prefix = ["--index-url", index_url] if index_url else []
    if deps:
        install_args = _install_requirements_for_extra(extra, deps)
        if install_args:
            return [*prefix, *install_args], f"{extra} support"
        return [], f"{extra} support"
    target = f"nanobot-ai[{extra}]"
    return [*prefix, target], f'"{target}"'


def _requirement_installed(req: Requirement, extra: str, seen: set[tuple[str, str]]) -> bool:
    if req.marker and not req.marker.evaluate({"extra": extra}):
        return True
    key = (
        canonicalize_name(req.name),
        ",".join(sorted(canonicalize_name(value) for value in req.extras)),
    )
    if key in seen:
        return True
    seen.add(key)
    try:
        dist = distribution(req.name)
    except PackageNotFoundError:
        return False
    if req.specifier and not req.specifier.contains(dist.version, prereleases=True):
        return False

    for requested_extra in req.extras:
        if not _extra_dependencies_installed(dist, requested_extra, seen):
            return False
    return True


def _extra_dependencies_installed(
    dist: Any,
    requested_extra: str,
    seen: set[tuple[str, str]],
) -> bool:
    normalized = canonicalize_name(requested_extra)
    provided = {
        canonicalize_name(value)
        for value in (dist.metadata.get_all("Provides-Extra") or [])
    }
    if provided and normalized not in provided:
        return False

    matched = False
    for raw in dist.requires or []:
        try:
            req = Requirement(raw)
        except Exception:
            continue
        if req.marker and not req.marker.evaluate({"extra": requested_extra}):
            continue
        matched = True
        if not _requirement_installed(req, requested_extra, seen):
            return False
    return matched or bool(provided)


def requirement_installed(raw: str, extra: str = "") -> bool:
    return _requirement_installed(Requirement(raw), extra, set())


def extra_installed(extra: str, deps: list[str] | None) -> bool:
    if deps is None:
        return True
    return all(requirement_installed(dep, extra) for dep in deps)


def run_install_command(argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_INSTALL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
        message = f"Timed out after {_INSTALL_TIMEOUT_SECONDS}s"
        stderr = "\n".join(part for part in ((stderr or "").rstrip(), message) if part)
        return subprocess.CompletedProcess(argv, 124, stdout=stdout or "", stderr=stderr)


def command_text(argv: list[str]) -> str:
    return subprocess.list2cmdline([str(part) for part in argv])


def _log_completed_command(label: str, proc: subprocess.CompletedProcess[str]) -> None:
    logger.info("{} exited with code {}", label, proc.returncode)
    output = (proc.stderr or proc.stdout or "").strip()
    if output:
        logger.info("{} output:\n{}", label, output[:_LOG_OUTPUT_LIMIT])


def missing_pip(proc: subprocess.CompletedProcess[str]) -> bool:
    return "no module named pip" in f"{proc.stdout}\n{proc.stderr}".lower()


def install_extra(
    extra: str,
    deps: list[str] | None,
    *,
    package_index: str = "default",
    runner: Any = run_install_command,
) -> InstallResult:
    import importlib

    install_args, label = install_args_for_extra(extra, deps, package_index=package_index)
    pip_cmd = [sys.executable, "-m", "pip", "install", *install_args]
    if not install_args:
        logger.info("Optional feature '{}' has no installable dependencies for this platform", extra)
        return InstallResult(True, label, pip_cmd)

    logger.info("Installing optional feature '{}': {}", extra, command_text(pip_cmd))
    proc = runner(pip_cmd)
    _log_completed_command(f"Optional feature '{extra}' install", proc)
    if proc.returncode == 0:
        importlib.invalidate_caches()
        return InstallResult(True, label, pip_cmd)

    failed_cmd = pip_cmd
    failed_proc = proc
    if missing_pip(proc):
        ensure_cmd = [sys.executable, "-m", "ensurepip", "--upgrade"]
        logger.info("pip missing while installing '{}'; running {}", extra, command_text(ensure_cmd))
        ensure_proc = runner(ensure_cmd)
        _log_completed_command(f"Optional feature '{extra}' ensurepip", ensure_proc)
        if ensure_proc.returncode == 0:
            logger.info("Retrying optional feature '{}': {}", extra, command_text(pip_cmd))
            proc = runner(pip_cmd)
            _log_completed_command(f"Optional feature '{extra}' install retry", proc)
            if proc.returncode == 0:
                importlib.invalidate_caches()
                return InstallResult(True, label, pip_cmd)
            failed_cmd = pip_cmd
            failed_proc = proc
        else:
            failed_cmd = ensure_cmd
            failed_proc = ensure_proc

        if uv := shutil.which("uv"):
            uv_cmd = [uv, "pip", "install", "--python", sys.executable, *install_args]
            logger.info("Retrying optional feature '{}' with uv: {}", extra, command_text(uv_cmd))
            proc = runner(uv_cmd)
            _log_completed_command(f"Optional feature '{extra}' uv install", proc)
            if proc.returncode == 0:
                importlib.invalidate_caches()
                return InstallResult(True, label, pip_cmd)
            failed_cmd = uv_cmd
            failed_proc = proc

    output = (failed_proc.stderr or failed_proc.stdout or "").strip()
    return InstallResult(False, label, pip_cmd, failed_cmd=failed_cmd, output=output)


def read_config_data(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_config_data(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def merge_missing_defaults(existing: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    merged = dict(defaults)
    for key, value in existing.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_missing_defaults(value, merged[key])
        else:
            merged[key] = value
    return merged


def enable_channel_config(config_path: Path, channel_name: str, defaults: dict[str, Any]) -> None:
    data = read_config_data(config_path)
    channels = data.setdefault("channels", {})
    existing = channels.get(channel_name, {})
    if not isinstance(existing, dict):
        existing = {}
    merged = merge_missing_defaults(existing, defaults)
    merged["enabled"] = True
    channels[channel_name] = merged
    write_config_data(config_path, data)


def disable_channel_config(config_path: Path, channel_name: str) -> None:
    data = read_config_data(config_path)
    channels = data.setdefault("channels", {})
    existing = channels.get(channel_name, {})
    if not isinstance(existing, dict):
        existing = {}
    existing["enabled"] = False
    channels[channel_name] = existing
    write_config_data(config_path, data)


def channel_enabled(config: Config, name: str) -> bool:
    section = getattr(config.channels, name, None)
    default_enabled = name in _DEFAULT_ENABLED_CHANNELS
    if section is None:
        return default_enabled
    if isinstance(section, dict):
        return bool(section.get("enabled", default_enabled))
    return bool(getattr(section, "enabled", default_enabled))


def optional_features_payload(
    *,
    config: Config | None = None,
    last_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from nanobot.channels.registry import discover_channel_names, discover_plugins
    from nanobot.config.loader import load_config

    config = config or load_config()
    extras = optional_dependency_groups()
    builtin_channels = set(discover_channel_names())
    plugin_channels = discover_plugins()
    features: list[dict[str, Any]] = []

    for name in sorted(builtin_channels | set(plugin_channels) | set(extras)):
        is_channel = name in builtin_channels or name in plugin_channels
        installed = extra_installed(name, extras[name]) if name in extras else True
        enabled = channel_enabled(config, name) if is_channel else installed
        ready = bool(enabled and installed)
        status = "enabled" if ready else "missing_dependency" if not installed else "not_enabled"
        features.append(
            {
                "name": name,
                "display_name": name.replace("_", " ").title(),
                "type": "channel" if is_channel else "feature",
                "enabled": enabled,
                "installed": installed,
                "ready": ready,
                "status": status,
                "install_supported": name in extras or is_channel,
                "requires_restart": is_channel or name in extras,
            }
        )

    payload = {
        "features": features,
        "enabled_count": sum(1 for feature in features if feature["ready"]),
    }
    if last_action:
        payload["last_action"] = last_action
    return payload


def enable_optional_feature(
    name: str,
    *,
    config_path: Path | None = None,
    allow_install: bool = True,
    runner: Any = run_install_command,
) -> dict[str, Any]:
    from nanobot.channels.registry import (
        discover_channel_names,
        discover_plugins,
        load_channel_class,
    )
    from nanobot.config.loader import get_config_path, load_config

    config_path = config_path or get_config_path()
    config = load_config(config_path)
    extras = optional_dependency_groups()
    builtin_channels = set(discover_channel_names())
    plugin_channels = discover_plugins()
    known = builtin_channels | set(plugin_channels) | set(extras)
    if name not in known:
        available = ", ".join(sorted(known))
        raise OptionalFeatureError(f"Unknown feature: {name}. Available: {available}", status=404)

    if name in extras and not extra_installed(name, extras[name]):
        if not allow_install:
            raise OptionalFeatureError(
                "Installing optional features from a remote WebUI is disabled. "
                "Run this action from localhost or set tools.webuiAllowRemotePackageInstall to true.",
                status=403,
            )
        result = install_extra(
            name,
            extras[name],
            package_index=config.tools.optional_feature_install_index,
            runner=runner,
        )
        if not result.ok:
            failed = command_text(result.failed_cmd or result.pip_cmd)
            detail = f": {result.output}" if result.output else ""
            raise OptionalFeatureError(f"Failed: {failed}{detail}", status=500)

    if name in builtin_channels:
        try:
            channel_cls = load_channel_class(name)
        except Exception as exc:
            raise OptionalFeatureError(
                f"Channel '{name}' is not importable after enable: {exc}",
                status=500,
            ) from exc
        enable_channel_config(config_path, name, channel_cls.default_config())
        message = f"Enabled channel '{name}'"
    elif name in plugin_channels:
        enable_channel_config(config_path, name, plugin_channels[name].default_config())
        message = f"Enabled channel '{name}'"
    else:
        message = f"Enabled feature '{name}'"

    payload = optional_features_payload(last_action={"ok": True, "message": message, "enabled": True})
    payload["requires_restart"] = bool(name in builtin_channels or name in plugin_channels or name in extras)
    return payload


def disable_optional_feature(
    name: str,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    from nanobot.channels.registry import discover_channel_names, discover_plugins
    from nanobot.config.loader import get_config_path

    config_path = config_path or get_config_path()
    extras = optional_dependency_groups()
    builtin_channels = set(discover_channel_names())
    plugin_channels = discover_plugins()
    known_channels = builtin_channels | set(plugin_channels)
    known = known_channels | set(extras)
    if name not in known:
        available = ", ".join(sorted(known))
        raise OptionalFeatureError(f"Unknown feature: {name}. Available: {available}", status=404)
    if name not in known_channels:
        raise OptionalFeatureError(f"Feature '{name}' cannot be disabled", status=400)
    if name == "websocket":
        raise OptionalFeatureError("Channel 'websocket' cannot be disabled", status=400)

    disable_channel_config(config_path, name)
    payload = optional_features_payload(
        last_action={"ok": True, "message": f"Disabled channel '{name}'", "enabled": False}
    )
    payload["requires_restart"] = True
    return payload
