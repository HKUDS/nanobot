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


def has_extra_marker(raw: str) -> bool:
    try:
        marker = Requirement(raw).marker
    except Exception:
        return False
    return marker is not None and "extra" in str(marker)


def install_args_for_extra(extra: str, deps: list[str] | None) -> tuple[list[str], str]:
    if deps and not any(has_extra_marker(dep) for dep in deps):
        return deps, f"{extra} support"
    target = f"nanobot-ai[{extra}]"
    return [target], f'"{target}"'


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


def missing_pip(proc: subprocess.CompletedProcess[str]) -> bool:
    return "no module named pip" in f"{proc.stdout}\n{proc.stderr}".lower()


def install_extra(
    extra: str,
    deps: list[str] | None,
    *,
    runner: Any = run_install_command,
) -> InstallResult:
    import importlib

    install_args, label = install_args_for_extra(extra, deps)
    pip_cmd = [sys.executable, "-m", "pip", "install", *install_args]

    proc = runner(pip_cmd)
    if proc.returncode == 0:
        importlib.invalidate_caches()
        return InstallResult(True, label, pip_cmd)

    failed_cmd = pip_cmd
    failed_proc = proc
    if missing_pip(proc):
        ensure_cmd = [sys.executable, "-m", "ensurepip", "--upgrade"]
        ensure_proc = runner(ensure_cmd)
        if ensure_proc.returncode == 0:
            proc = runner(pip_cmd)
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
            proc = runner(uv_cmd)
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


def channel_enabled(config: Config, name: str) -> bool:
    section = getattr(config.channels, name, None)
    if section is None:
        return False
    if isinstance(section, dict):
        return bool(section.get("enabled", False))
    return bool(getattr(section, "enabled", False))


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
    runner: Any = run_install_command,
) -> dict[str, Any]:
    from nanobot.channels.registry import (
        discover_channel_names,
        discover_plugins,
        load_channel_class,
    )
    from nanobot.config.loader import get_config_path

    config_path = config_path or get_config_path()
    extras = optional_dependency_groups()
    builtin_channels = set(discover_channel_names())
    plugin_channels = discover_plugins()
    known = builtin_channels | set(plugin_channels) | set(extras)
    if name not in known:
        available = ", ".join(sorted(known))
        raise OptionalFeatureError(f"Unknown feature: {name}. Available: {available}", status=404)

    if name in extras and not extra_installed(name, extras[name]):
        result = install_extra(name, extras[name], runner=runner)
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
