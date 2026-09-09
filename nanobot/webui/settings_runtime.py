"""Explicit non-channel runtime configuration exposed by the settings UI."""

from __future__ import annotations

import ipaddress
import math
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, cast

from pydantic import BaseModel, TypeAdapter, ValidationError

from nanobot.config.schema import Config
from nanobot.security.network import is_loopback_host
from nanobot.webui.settings_contracts import WebUISettingsError

# Only these leaves may be read or patched through this surface. Model/provider,
# channel, and secret configuration keep their dedicated mutation contracts.
RUNTIME_CONFIG_PATHS = (
    "agents.defaults.timezone",
    "agents.defaults.timezone_mode",
    "agents.defaults.unified_session",
    "agents.defaults.max_tool_iterations",
    "agents.defaults.max_concurrent_subagents",
    "agents.defaults.max_tool_result_chars",
    "agents.defaults.provider_retry_mode",
    "agents.defaults.tool_hint_max_length",
    "agents.defaults.dream.enabled",
    "gateway.host",
    "gateway.port",
    "gateway.restart_mode",
    "tools.exec.enable",
    "tools.exec.timeout",
    "tools.exec.path_prepend",
    "tools.exec.path_append",
    "tools.exec.sandbox",
    "tools.exec.sandbox_ro_binds",
    "tools.exec.sandbox_rw_binds",
    "tools.exec.allowed_env_keys",
    "tools.exec.allow_patterns",
    "tools.exec.deny_patterns",
    "tools.file.enable",
    "tools.my.enable",
    "tools.my.allow_set",
    "tools.cli_apps.enable",
    "tools.cli_apps.install_timeout",
    "tools.cli_apps.run_timeout",
    "tools.cli_apps.catalog_ttl_seconds",
    "tools.restrict_to_workspace",
    "tools.ssrf_whitelist",
    "tools.max_session_messages_per_minute",
    "tools.webui_allow_remote_package_install",
    "tools.web.enable",
    "tools.web.proxy",
    "tools.web.user_agent",
    "tools.image_generation.save_dir",
    "api.host",
    "api.timeout",
)


def _parent(config: Config, path: str) -> tuple[BaseModel, str]:
    parent: BaseModel = config
    *parts, leaf = path.split(".")
    for part in parts:
        value: object = getattr(parent, part)
        assert isinstance(value, BaseModel)
        parent = value
    return parent, leaf


def runtime_config_payload(config: Config) -> dict[str, Any]:
    return {
        path: getattr(parent, leaf)
        for path in RUNTIME_CONFIG_PATHS
        for parent, leaf in [_parent(config, path)]
    }


def update_runtime_config(
    config: Config, values: dict[str, Any], *, local_browser: bool,
) -> bool:
    """Validate the complete patch before changing any persisted configuration."""
    unknown = values.keys() - set(RUNTIME_CONFIG_PATHS)
    if unknown:
        raise WebUISettingsError("Unknown runtime setting: " + sorted(unknown)[0])
    remote_install = "tools.webui_allow_remote_package_install"
    if remote_install in values and not local_browser:
        if values[remote_install] != config.tools.webui_allow_remote_package_install:
            raise WebUISettingsError(
                "Change remote installation access from a browser on the gateway host.",
                status=403,
            )
    candidate = config.model_copy(deep=True)
    for path, value in values.items():
        parent, leaf = _parent(candidate, path)
        if isinstance(value, float) and not math.isfinite(value):
            raise WebUISettingsError(f"{path}: enter a finite number")
        try:
            field = type(parent).model_fields[leaf]
            parsed = TypeAdapter(field.rebuild_annotation()).validate_python(value, strict=True)
        except ValidationError as exc:
            message = exc.errors(include_input=False, include_url=False)[0]["msg"]
            raise WebUISettingsError(f"{path}: {message}") from None
        setattr(parent, leaf, parsed)
    try:
        # Dump aliases so legacy field names and timezone/model validators are
        # handled by the same schema as a normal configuration-file load.
        validated = Config.model_validate(candidate.model_dump(by_alias=True), strict=True)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_url=False)
        error = errors[0]
        location = ".".join(str(part) for part in error["loc"])
        raise WebUISettingsError(f"{location}: {error['msg']}") from None

    numeric_minima = {
        "agents.defaults.max_tool_iterations": 1,
        "agents.defaults.max_tool_result_chars": 1,
        "gateway.port": 1,
        "api.timeout": 1,
    }
    for path, minimum in numeric_minima.items():
        if path in values:
            parent, leaf = _parent(validated, path)
            if getattr(parent, leaf) < minimum:
                raise WebUISettingsError(f"{path}: must be at least {minimum}")
    if "gateway.port" in values and validated.gateway.port > 65535:
        raise WebUISettingsError("gateway.port: must be at most 65535")
    if "api.timeout" in values and validated.api.timeout > 3600:
        raise WebUISettingsError("api.timeout: must be at most 3600 seconds")
    for path in ("gateway.host", "api.host", "tools.image_generation.save_dir"):
        if path in values:
            parent, leaf = _parent(validated, path)
            if not str(getattr(parent, leaf)).strip():
                raise WebUISettingsError(f"{path}: must not be empty")
    if "tools.image_generation.save_dir" in values:
        directory = validated.tools.image_generation.save_dir
        if (PureWindowsPath(directory).drive or directory.startswith(("/", "\\"))
                or ".." in PurePosixPath(directory.replace("\\", "/")).parts):
            raise WebUISettingsError("tools.image_generation.save_dir: use a relative path inside the media directory")
    if "api.host" in values and not is_loopback_host(validated.api.host):
        if not validated.api.api_key.strip():
            raise WebUISettingsError("Set an API key in System before using a network bind address.")
    if "tools.exec.sandbox" in values and validated.tools.exec.sandbox not in {"", "bwrap"}:
        raise WebUISettingsError("tools.exec.sandbox: choose no sandbox or bwrap")
    if "tools.ssrf_whitelist" in values:
        for cidr in validated.tools.ssrf_whitelist:
            try:
                ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                raise WebUISettingsError("tools.ssrf_whitelist: enter valid IP addresses or CIDR ranges") from None
    for path in ("tools.exec.allow_patterns", "tools.exec.deny_patterns"):
        if path in values:
            patterns = cast(list[str], values[path])  # Schema validation above guarantees list[str].
            for pattern in patterns:
                try:
                    re.compile(pattern)
                except re.error:
                    raise WebUISettingsError(f"{path}: invalid regular expression") from None
    before = runtime_config_payload(config)
    after = runtime_config_payload(validated)
    if before == after:
        return False
    config.agents = validated.agents
    config.tools = validated.tools
    config.gateway = validated.gateway
    config.api = validated.api
    return True
