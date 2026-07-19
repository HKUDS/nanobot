"""Optional nanobot feature discovery and enablement."""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any

from loguru import logger
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from nanobot.channels._setup import channel_setup_spec
from nanobot.channels.contracts import (
    ChannelSetupSpec,
    channel_feature_instances,
    channel_field_value,
    channel_instance_specs,
    channel_local_state_present,
    channel_set_config_enabled,
    channel_value_present,
    refresh_channel_feature_metadata,
    resolve_channel_action_target,
    stringify_channel_value,
)
from nanobot.channels.registry import channel_default_enabled
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
_LOG_OUTPUT_LIMIT = 4000
_HIDDEN_OPTIONAL_FEATURES = {"documents", "pdf"}
_BUNDLED_FEATURE_ALIASES = {"documents", "pdf"}


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
            if name != "dev" and name not in _HIDDEN_OPTIONAL_FEATURES and isinstance(values, list)
        }
    return {
        name: values
        for name, values in optional_dependency_groups_from_metadata().items()
        if name not in _HIDDEN_OPTIONAL_FEATURES
    }


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


def install_args_for_extra(
    extra: str,
    deps: list[str] | None,
) -> tuple[list[str], str]:
    if deps:
        install_args = _install_requirements_for_extra(extra, deps)
        if install_args:
            return install_args, f"{extra} support"
        return [], f"{extra} support"
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
    runner: Any = run_install_command,
) -> InstallResult:
    import importlib

    install_args, label = install_args_for_extra(extra, deps)
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


def set_channel_config_enabled(
    config_path: Path,
    channel_name: str,
    plugin: Any,
    enabled: bool,
    *,
    instance_id: str | None = "default",
) -> None:
    """Persist one instance, or the top-level plugin gate when the target is ``None``."""
    data = read_config_data(config_path)
    channels = data.setdefault("channels", {})
    existing = channels.get(channel_name, {})
    if not isinstance(existing, dict):
        existing = {}
    if instance_id is None:
        existing["enabled"] = enabled
        channels[channel_name] = existing
    else:
        try:
            channels[channel_name] = channel_set_config_enabled(
                plugin,
                existing,
                enabled,
                instance_id=instance_id,
            )
        except ValueError as exc:
            raise OptionalFeatureError(
                f"Invalid {channel_name} configuration: {exc}",
                status=400,
            ) from exc
    write_config_data(config_path, data)


def channel_enabled(
    config: Config,
    name: str,
    plugin: Any | None = None,
    *,
    default_enabled: bool | None = None,
) -> bool:
    section = getattr(config.channels, name, None)
    if default_enabled is None:
        default_enabled = plugin.default_enabled if plugin is not None else channel_default_enabled(name)
    if section is None:
        return default_enabled
    if plugin is None:
        from nanobot.channels.registry import load_channel_plugin

        plugin = load_channel_plugin(name)
    return bool(channel_instance_specs(plugin, section, enabled_only=True))


def _channel_config_snapshot(
    section: Any,
    name: str,
    spec: ChannelSetupSpec | None,
) -> tuple[dict[str, str], list[str]]:
    if hasattr(section, "model_dump"):
        section = section.model_dump(mode="json", by_alias=True)
    if not isinstance(section, dict):
        return {}, []

    if spec is None:
        return {}, []

    values: dict[str, str] = {}
    configured_fields: list[str] = []
    for field in spec.snapshot_fields:
        value = channel_field_value(section, field)
        if not channel_value_present(value):
            continue
        key = f"channels.{name}.{field}"
        configured_fields.append(key)
        if field in spec.secrets:
            continue
        values[key] = stringify_channel_value(value)
    return values, configured_fields


def _channel_has_required_setup(section: Any, spec: ChannelSetupSpec | None) -> bool:
    return bool(spec and spec.is_configured(section))


def channel_configured(
    config: Config,
    name: str,
    spec: ChannelSetupSpec | None = None,
    plugin: Any | None = None,
    *,
    default_enabled: bool | None = None,
) -> bool:
    """Return whether a channel has enough saved setup to be enabled directly."""
    section = getattr(config.channels, name, None)
    if plugin is None:
        from nanobot.channels.registry import load_channel_plugin

        plugin = load_channel_plugin(name)

    if channel_local_state_present(plugin, section):
        return True
    if section is None:
        return False

    if plugin.management.multi_instance:
        return any(
            _channel_has_required_setup(instance.config, spec)
            for instance in channel_instance_specs(
                plugin,
                section,
                enabled_only=False,
            )
        )

    if not spec or not spec.required:
        return channel_enabled(
            config,
            name,
            plugin,
            default_enabled=default_enabled,
        )
    return _channel_has_required_setup(section, spec)


def _feature_dependencies(
    name: str,
    channel_plugin: Any | None,
    extras: dict[str, list[str] | None],
) -> list[str] | None:
    if channel_plugin is not None:
        return list(channel_plugin.dependencies)
    return extras.get(name)


def install_optional_feature_dependencies(
    name: str,
    *,
    runner: Any = run_install_command,
) -> dict[str, Any]:
    """Install declared requirements without enabling or importing a channel runtime."""
    from nanobot.channels.registry import discover_plugins

    if name in _BUNDLED_FEATURE_ALIASES:
        return {
            "ok": True,
            "changed": False,
            "message": f"Feature '{name}' is included with nanobot",
        }

    extras = optional_dependency_groups()
    channel_plugins = discover_plugins()
    known = set(channel_plugins) | set(extras)
    if name not in known:
        available = ", ".join(sorted(known))
        raise OptionalFeatureError(f"Unknown feature: {name}. Available: {available}", status=404)

    dependencies = _feature_dependencies(name, channel_plugins.get(name), extras)
    if not dependencies:
        return {
            "ok": True,
            "changed": False,
            "message": f"Feature '{name}' has no additional dependencies",
        }
    if extra_installed(name, dependencies):
        return {
            "ok": True,
            "changed": False,
            "message": f"Dependencies for '{name}' are already installed",
        }

    result = install_extra(name, dependencies, runner=runner)
    if not result.ok:
        failed = command_text(result.failed_cmd or result.pip_cmd)
        detail = f": {result.output}" if result.output else ""
        raise OptionalFeatureError(f"Failed: {failed}{detail}", status=500)
    return {
        "ok": True,
        "changed": True,
        "message": f"Installed dependencies for '{name}'",
    }


def optional_features_payload(
    *,
    config: Config | None = None,
    last_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from nanobot.channels.registry import discover_plugins
    from nanobot.config.loader import load_config

    config = config or load_config()
    extras = optional_dependency_groups()
    channel_plugins = discover_plugins()
    features: list[dict[str, Any]] = []

    feature_names = set(channel_plugins) | set(extras)
    for name in sorted(feature_names):
        channel_plugin = channel_plugins.get(name)
        is_channel = channel_plugin is not None
        dependencies = _feature_dependencies(name, channel_plugin, extras)
        has_dependencies = bool(dependencies)
        installed = extra_installed(name, dependencies) if has_dependencies else True
        feature = {
            "name": name,
            "display_name": (
                channel_plugin.display_name
                if channel_plugin is not None
                else name.replace("_", " ").title()
            ),
            "type": "channel" if is_channel else "feature",
            "installed": installed,
            "install_supported": has_dependencies or is_channel,
            "requires_restart": _feature_requires_restart(name, is_channel=is_channel),
        }
        if channel_plugin is not None:
            feature["capabilities"] = sorted(channel_plugin.capabilities)
            feature["settings_visible"] = channel_plugin.settings_visible
            if channel_plugin.webui is not None:
                feature["webui"] = channel_plugin.webui

        if not is_channel:
            feature.update({
                "enabled": installed,
                "configured": installed,
                "ready": installed,
                "status": "enabled" if installed else "missing_dependency",
            })
            features.append(feature)
            continue

        try:
            assert channel_plugin is not None
            setup_spec = channel_setup_spec(name, plugin=channel_plugin)
            if setup_spec is not None:
                feature["setup"] = setup_spec.to_public_dict(name)
            enabled = channel_enabled(
                config,
                name,
                channel_plugin,
                default_enabled=channel_plugin.default_enabled,
            )
            configured = channel_configured(
                config,
                name,
                setup_spec,
                channel_plugin,
                default_enabled=channel_plugin.default_enabled,
            )
            ready = bool(enabled and installed)
            status = "enabled" if ready else "missing_dependency" if not installed else "not_enabled"
            feature.update({
                "enabled": enabled,
                "configured": configured,
                "ready": ready,
                "status": status,
            })
            config_values, configured_fields = _channel_config_snapshot(
                getattr(config.channels, name, None),
                name,
                setup_spec,
            )
            if config_values:
                feature["config_values"] = config_values
            if configured_fields:
                feature["configured_fields"] = configured_fields
            instances = channel_feature_instances(
                channel_plugin,
                getattr(config.channels, name, None),
                setup_spec=setup_spec,
            )
            if instances is not None:
                feature["instances"] = instances
        except Exception as exc:
            logger.warning("Could not inspect {} channel configuration: {}", name, exc)
            feature.update({
                "enabled": False,
                "configured": False,
                "ready": False,
                "status": "invalid_config",
                "error": "Channel configuration could not be inspected.",
            })
        features.append(feature)

    payload = {
        "features": features,
        "enabled_count": sum(1 for feature in features if feature["enabled"]),
    }
    if last_action:
        payload["last_action"] = last_action
    return payload


def with_channel_runtime_status(
    payload: dict[str, Any],
    runtime_status: dict[str, Any],
) -> dict[str, Any]:
    """Overlay live ChannelManager state on configuration-derived features."""
    statuses_by_owner: dict[str, list[dict[str, Any]]] = {}
    for status in runtime_status.values():
        if not isinstance(status, dict):
            continue
        owner = status.get("owner")
        if isinstance(owner, str):
            statuses_by_owner.setdefault(owner, []).append(status)

    features: list[dict[str, Any]] = []
    for original in payload.get("features", []):
        feature = dict(original)
        if feature.get("type") != "channel":
            features.append(feature)
            continue

        desired_enabled = bool(feature.get("enabled"))
        owner_statuses = statuses_by_owner.get(str(feature.get("name")), [])
        if desired_enabled and not owner_statuses:
            owner_statuses = [{
                "state": "failed",
                "running": False,
                "error": "Enabled channel has no runtime. Check gateway logs.",
            }]

        instances = feature.get("instances")
        if isinstance(instances, list):
            by_instance = {
                str(status.get("instance_id", "default")): status
                for status in owner_statuses
            }
            decorated_instances = []
            for original_instance in instances:
                instance = dict(original_instance)
                desired_instance = bool(instance.get("enabled"))
                status = by_instance.get(str(instance.get("id", "default")))
                if desired_instance and status is None:
                    status = {
                        "state": "failed",
                        "running": False,
                        "error": "Enabled channel instance has no runtime. Check gateway logs.",
                    }
                    owner_statuses.append(status)
                state = str(status.get("state", "stopped")) if status else "stopped"
                instance["runtime_status"] = state
                instance["running"] = state == "running"
                if status and status.get("error"):
                    instance["runtime_error"] = str(status["error"])
                decorated_instances.append(instance)
            feature["instances"] = decorated_instances

        state = _combined_channel_runtime_state(owner_statuses, desired_enabled)
        feature["runtime_status"] = state
        feature["running"] = state == "running"
        feature["ready"] = state == "running"
        feature["status"] = "enabled" if state == "running" else state
        error = next(
            (
                str(status["error"])
                for status in owner_statuses
                if status.get("error")
            ),
            None,
        )
        if error:
            feature["runtime_error"] = error
        features.append(feature)

    decorated = dict(payload)
    decorated["features"] = features
    decorated["enabled_count"] = sum(
        1
        for feature in features
        if (
            feature.get("running")
            if feature.get("type") == "channel"
            else feature.get("enabled")
        )
    )
    return decorated


def _combined_channel_runtime_state(
    statuses: list[dict[str, Any]],
    desired_enabled: bool,
) -> str:
    if not desired_enabled:
        return "stopped"
    states = {str(status.get("state", "stopped")) for status in statuses}
    if "failed" in states:
        return "failed"
    if "running" in states:
        return "running"
    if "starting" in states:
        return "starting"
    return "stopped"


def enable_optional_feature(
    name: str,
    *,
    config_path: Path | None = None,
    allow_install: bool = True,
    instance_id: str | None = None,
    runner: Any = run_install_command,
) -> dict[str, Any]:
    from nanobot.channels.registry import discover_plugins
    from nanobot.config.loader import get_config_path

    if name in _BUNDLED_FEATURE_ALIASES:
        payload = optional_features_payload(
            last_action={
                "ok": True,
                "message": f"Feature '{name}' is included with nanobot",
                "enabled": True,
            }
        )
        payload["requires_restart"] = False
        return payload
    config_path = config_path or get_config_path()
    requested_instance_id = (instance_id or "").strip() or None
    extras = optional_dependency_groups()
    channel_plugins = discover_plugins()
    known = set(channel_plugins) | set(extras)
    if name not in known:
        available = ", ".join(sorted(known))
        raise OptionalFeatureError(f"Unknown feature: {name}. Available: {available}", status=404)

    channel_plugin = channel_plugins.get(name)
    dependencies = _feature_dependencies(name, channel_plugin, extras)
    if dependencies and not extra_installed(name, dependencies):
        if not allow_install:
            raise OptionalFeatureError(
                "Installing optional features from a remote WebUI is disabled. "
                "Run this action from localhost or set tools.webuiAllowRemotePackageInstall to true.",
                status=403,
            )
        result = install_extra(
            name,
            dependencies,
            runner=runner,
        )
        if not result.ok:
            failed = command_text(result.failed_cmd or result.pip_cmd)
            detail = f": {result.output}" if result.output else ""
            raise OptionalFeatureError(f"Failed: {failed}{detail}", status=500)

    channel_cls: Any | None = None
    target_instance_id: str | None = None
    if channel_plugin is not None:
        try:
            channel_cls = channel_plugin.load_channel_class()
        except Exception as exc:
            raise OptionalFeatureError(
                f"Channel '{name}' is not importable after enable: {exc}",
                status=500,
            ) from exc
        target_instance_id = resolve_channel_action_target(
            requested_instance_id,
        )
        set_channel_config_enabled(
            config_path,
            name,
            channel_plugin,
            True,
            instance_id=target_instance_id,
        )
        message = f"Enabled channel '{name}'"
    else:
        message = f"Enabled feature '{name}'"

    if channel_cls is not None and target_instance_id is not None:
        try:
            refresh_channel_feature_metadata(
                channel_cls,
                config_path,
                instance_id=target_instance_id,
            )
        except Exception as exc:
            logger.warning("Could not refresh {} channel metadata: {}", name, exc)

    from nanobot.config.loader import load_config

    payload = optional_features_payload(
        config=load_config(config_path),
        last_action={"ok": True, "message": message, "enabled": True},
    )
    payload["requires_restart"] = _feature_requires_restart(
        name,
        is_channel=channel_plugin is not None,
    )
    return payload


def ensure_enabled_channel_dependencies(
    enabled_names: set[str],
    plugins: dict[str, Any],
    *,
    runner: Any = run_install_command,
) -> dict[str, str]:
    """Install requirements declared by enabled channel manifests.

    Returns user-safe errors keyed by channel name. Detailed installer output
    remains in gateway logs.
    """
    failures: dict[str, str] = {}
    for name in sorted(enabled_names):
        plugin = plugins.get(name)
        if plugin is None:
            continue
        dependencies = list(plugin.dependencies)
        if not dependencies or extra_installed(name, dependencies):
            continue
        result = install_extra(name, dependencies, runner=runner)
        if result.ok and extra_installed(name, dependencies):
            continue
        failures[name] = "Channel dependencies could not be installed. Check gateway logs."
        logger.error("Could not prepare dependencies for enabled channel '{}'", name)
    return failures


def _feature_requires_restart(name: str, *, is_channel: bool) -> bool:
    """Return whether an installed feature needs the running engine rebuilt."""
    if is_channel:
        return True
    # These libraries are imported lazily or used by a newly spawned service.
    return name not in {"api", "documents", "pdf", "olostep"}


def disable_optional_feature(
    name: str,
    *,
    config_path: Path | None = None,
    instance_id: str | None = None,
) -> dict[str, Any]:
    from nanobot.channels.registry import discover_plugins
    from nanobot.config.loader import get_config_path, load_config

    config_path = config_path or get_config_path()
    requested_instance_id = (instance_id or "").strip() or None
    extras = optional_dependency_groups()
    channel_plugins = discover_plugins()
    known_channels = set(channel_plugins)
    known = known_channels | set(extras)
    if name not in known:
        available = ", ".join(sorted(known))
        raise OptionalFeatureError(f"Unknown feature: {name}. Available: {available}", status=404)
    if name not in known_channels:
        raise OptionalFeatureError(f"Feature '{name}' cannot be disabled", status=400)
    channel_plugin = channel_plugins[name]
    target_instance_id = resolve_channel_action_target(requested_instance_id)
    set_channel_config_enabled(
        config_path,
        name,
        channel_plugin,
        False,
        instance_id=target_instance_id,
    )
    payload = optional_features_payload(
        config=load_config(config_path),
        last_action={"ok": True, "message": f"Disabled channel '{name}'", "enabled": False}
    )
    payload["requires_restart"] = True
    return payload
