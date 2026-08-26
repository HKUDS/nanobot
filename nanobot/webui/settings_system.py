"""System and channel settings domain logic."""

from __future__ import annotations

import asyncio
import inspect
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, cast
from zoneinfo import ZoneInfo

from nanobot.channels._setup import channel_setup_spec
from nanobot.channels.connect import ChannelConnectError
from nanobot.channels.contracts import (
    RouteFieldType,
    channel_instance_config,
    channel_update_instance_config,
)
from nanobot.config.schema import Config
from nanobot.llm_usage import llm_usage_payload
from nanobot.optional_features import OptionalFeatureError, with_channel_runtime_status
from nanobot.security.workspace_access import workspace_sandbox_status
from nanobot.webui.settings_capabilities import network_safety_payload
from nanobot.webui.settings_contracts import (
    QueryParams,
    SettingsRequest,
    SettingsRouteResult,
    WebUISettingsError,
    query_first,
    query_first_alias,
)

if TYPE_CHECKING:
    from nanobot.webui.settings_services import WebUISettingsServices

LoadChannelPlugin = Callable[[str], Any]
ListPendingPairings = Callable[[], Iterable[dict[str, Any]]]
SettingsOperation = Callable[..., Any]


@dataclass(frozen=True)
class SystemSettingsOperations:
    cli_apps_payload: SettingsOperation
    cli_apps_action: SettingsOperation
    nanobot_features_payload: SettingsOperation
    nanobot_features_action: SettingsOperation
    nanobot_feature_instance_target: SettingsOperation
    validate_channel_config: SettingsOperation
    load_channel_plugin: LoadChannelPlugin
    list_pending: ListPendingPairings
    approve_code: SettingsOperation
    deny_code: SettingsOperation
    mcp_presets_action: SettingsOperation
    reload_mcp: SettingsOperation
    mcp_runtime_status: Callable[[], Mapping[str, str]] | None
    check_for_update: SettingsOperation
    channel_feature_action: SettingsOperation | None = None
    channel_runtime_status: Callable[[], dict[str, Any]] | None = None


class SystemSettingsPayload(TypedDict):
    runtime: dict[str, Any]
    usage: dict[str, Any]
    advanced: dict[str, Any]
    version: dict[str, Any]
    docs: dict[str, Any]


_DOCS_STABLE_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:\.post\d+)?$")
_DOCS_LATEST_URL = "https://nanobot.wiki/docs/latest"
_SKIP_FIELD = object()


def docs_version(version: str) -> str:
    """Map package versions to the matching public docs path."""
    normalized = version.strip()
    if _DOCS_STABLE_VERSION_RE.fullmatch(normalized):
        return normalized
    return "latest"


def docs_payload(version: str) -> dict[str, Any]:
    selected_version = docs_version(version)
    base_url = f"https://nanobot.wiki/docs/{selected_version}"
    return {
        "version": selected_version,
        "base_url": base_url,
        "chat_apps_url": f"{base_url}/getting-started/chat-apps",
        "latest_url": _DOCS_LATEST_URL,
    }


def system_settings_payload(
    config: Config,
    *,
    config_path: Path,
    version: str,
) -> SystemSettingsPayload:
    defaults = config.agents.defaults
    exec_config = config.tools.exec
    sandbox_status = workspace_sandbox_status(
        restrict_to_workspace=config.tools.restrict_to_workspace,
        workspace=config.workspace_path,
    )
    return {
        "runtime": {
            "config_path": str(config_path.expanduser()),
            "workspace_path": str(config.workspace_path),
            "gateway_host": config.gateway.host,
            "gateway_port": config.gateway.port,
            "heartbeat": {
                "enabled": config.gateway.heartbeat.enabled,
                "interval_s": config.gateway.heartbeat.interval_s,
                "keep_recent_messages": config.gateway.heartbeat.keep_recent_messages,
            },
            "dream": {
                "schedule": defaults.dream.describe_schedule(),
            },
            "unified_session": defaults.unified_session,
        },
        "usage": llm_usage_payload(timezone_name=defaults.timezone),
        "advanced": {
            "restrict_to_workspace": config.tools.restrict_to_workspace,
            "workspace_sandbox": sandbox_status.as_dict(),
            **network_safety_payload(config),
            "mcp_server_count": len(config.tools.mcp_servers),
            "exec_enabled": exec_config.enable,
            "exec_sandbox": exec_config.sandbox or None,
            "exec_path_prepend_set": bool(exec_config.path_prepend),
            "exec_path_append_set": bool(exec_config.path_append),
        },
        "version": {"current": version},
        "docs": docs_payload(version),
    }


def settings_usage_payload(config: Config) -> dict[str, Any]:
    """Return the lightweight token usage slice for Overview refreshes."""
    return llm_usage_payload(timezone_name=config.agents.defaults.timezone)


def update_agent_system_settings(config: Config, query: QueryParams) -> tuple[bool, bool]:
    defaults = config.agents.defaults
    changed = False
    restart_required = False

    timezone = query_first(query, "timezone")
    if timezone is not None:
        timezone = timezone.strip()
        if not timezone:
            raise WebUISettingsError("timezone is required")
        try:
            ZoneInfo(timezone)
        except Exception:
            raise WebUISettingsError("invalid timezone") from None
        timezone_changed = defaults.timezone != timezone
        if timezone_changed or defaults.timezone_mode != "manual":
            defaults.timezone = timezone
            defaults.timezone_mode = "manual"
            changed = True
            restart_required = timezone_changed

    tool_hint_max_length = query_first_alias(
        query,
        "tool_hint_max_length",
        "toolHintMaxLength",
    )
    if tool_hint_max_length is not None:
        try:
            parsed = int(tool_hint_max_length)
        except ValueError:
            raise WebUISettingsError(
                "tool_hint_max_length must be an integer"
            ) from None
        if parsed < 20 or parsed > 500:
            raise WebUISettingsError(
                "tool_hint_max_length must be between 20 and 500"
            )
        if defaults.tool_hint_max_length != parsed:
            defaults.tool_hint_max_length = parsed
            changed = True
            restart_required = True
    return changed, restart_required


def save_channel_config_values(
    config: Config,
    name: str,
    raw_values: dict[str, Any],
    instance_id: str = "default",
    *,
    load_channel_plugin: LoadChannelPlugin,
) -> list[str]:
    if not name:
        raise WebUISettingsError("missing channel name")
    try:
        plugin = load_channel_plugin(name)
    except ImportError:
        raise WebUISettingsError(f"unknown channel '{name}'", status=404) from None
    setup_spec = channel_setup_spec(name, plugin=plugin)
    if setup_spec is None:
        raise WebUISettingsError(
            f"channel '{name}' cannot be configured from WebUI",
            status=404,
        )
    field_types = setup_spec.route_field_types
    if not raw_values:
        return []

    section = getattr(config.channels, name, None)
    channel_config = channel_instance_config(
        plugin,
        section,
        instance_id=instance_id,
    )
    saved: list[str] = []
    prefix = f"channels.{name}."
    for raw_key, raw_value in raw_values.items():
        if not raw_key:
            raise WebUISettingsError(
                "channel settings payload contains an invalid key"
            )
        field = raw_key[len(prefix) :] if raw_key.startswith(prefix) else raw_key
        value_type = field_types.get(field)
        if value_type is None:
            raise WebUISettingsError(f"'{raw_key}' cannot be configured from WebUI")
        value = coerce_channel_value(raw_key, raw_value, value_type)
        if value is _SKIP_FIELD:
            continue
        assign_channel_config_value(channel_config, field, value)
        saved.append(raw_key)

    try:
        updated_section = channel_update_instance_config(
            plugin,
            section,
            channel_config,
            instance_id=instance_id,
        )
    except ValueError as exc:
        raise WebUISettingsError(
            f"Invalid {name} configuration: {exc}",
            status=400,
        ) from exc
    setattr(config.channels, name, updated_section)
    return saved


def coerce_channel_value(
    raw_key: str,
    raw_value: Any,
    value_type: RouteFieldType,
) -> Any:
    if isinstance(value_type, tuple):
        kind = value_type[0]
        allowed = value_type[1]
    else:
        kind = value_type
        allowed = None

    if kind in {"string", "secret"}:
        value = raw_value.strip() if isinstance(raw_value, str) else str(raw_value)
        if kind == "secret" and not value:
            return _SKIP_FIELD
        return value

    if kind == "list":
        if raw_value is None:
            return []
        if isinstance(raw_value, str):
            return [item.strip() for item in raw_value.split(",") if item.strip()]
        if isinstance(raw_value, list):
            return [
                str(item).strip()
                for item in cast(list[Any], raw_value)
                if str(item).strip()
            ]
        raise WebUISettingsError(f"'{raw_key}' must be a comma-separated list")

    if kind == "int":
        if raw_value in (None, ""):
            return _SKIP_FIELD
        try:
            return int(raw_value)
        except (TypeError, ValueError) as exc:
            raise WebUISettingsError(f"'{raw_key}' must be a number") from exc

    if kind == "bool":
        if isinstance(raw_value, bool):
            return raw_value
        value = str(raw_value).strip().lower()
        if value in {"true", "1", "yes", "on"}:
            return True
        if value in {"false", "0", "no", "off"}:
            return False
        raise WebUISettingsError(f"'{raw_key}' must be true or false")

    if kind == "enum":
        value = raw_value.strip() if isinstance(raw_value, str) else str(raw_value)
        if not value:
            return _SKIP_FIELD
        if allowed is None or value not in allowed:
            options = ", ".join(sorted(allowed or ()))
            raise WebUISettingsError(f"'{raw_key}' must be one of: {options}")
        return value

    raise WebUISettingsError(f"'{raw_key}' has an unsupported field type")


def assign_channel_config_value(
    channel_config: dict[str, Any],
    field: str,
    value: Any,
) -> None:
    target = channel_config
    parts = field.split(".")
    for part in parts[:-1]:
        current: object = target.get(part)
        if not isinstance(current, dict):
            current = {}
            target[part] = current
        target = cast(dict[str, Any], current)
    target[parts[-1]] = value


def pairing_payload(
    list_pending: ListPendingPairings,
    last_action: dict[str, Any] | None = None,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    current_time = time.time() if now is None else now
    requests: list[dict[str, Any]] = []
    for item in list_pending():
        expires_at = float(item.get("expires_at", 0) or 0)
        created_at = float(item.get("created_at", 0) or 0)
        requests.append(
            {
                "code": str(item.get("code", "")),
                "channel": str(item.get("channel", "")),
                "sender_id": str(item.get("sender_id", "")),
                "created_at_ms": int(created_at * 1000) if created_at else None,
                "expires_at_ms": int(expires_at * 1000) if expires_at else None,
                "expires_in_seconds": (
                    max(0, int(expires_at - current_time)) if expires_at else None
                ),
            }
        )
    payload: dict[str, Any] = {"requests": requests}
    if last_action is not None:
        payload["last_action"] = last_action
    return payload


class SystemSettingsHandler:
    """Handle channel and system commands behind a transport-neutral request DTO."""

    def __init__(self, settings: WebUISettingsServices, logger: Any) -> None:
        self.settings = settings
        self.logger = logger
        self._channel_connectors: dict[str, Any] = {}

    async def handle(
        self,
        action: str,
        request: SettingsRequest,
        operations: SystemSettingsOperations,
        *,
        channel_name: str | None = None,
        connect_action: str | None = None,
    ) -> SettingsRouteResult:
        if action == "cli-list":
            return await self._cli_apps(request, operations)
        if action.startswith("cli-"):
            return await self._cli_apps_action(
                request,
                action.removeprefix("cli-"),
                operations,
            )
        if action == "features-list":
            return await self._features(operations)
        if action in {"features-enable", "features-disable"}:
            return await self._features_action(
                request,
                action.removeprefix("features-"),
                operations,
            )
        if action == "channel-validate":
            return await self._channel_validate(request, operations)
        if action == "channel-configure":
            return await self._channel_configure(request, operations)
        if action == "channel-connect" and channel_name and connect_action:
            return await self._channel_connect(
                request,
                channel_name,
                connect_action,
                operations,
            )
        if action == "pairing-list":
            return SettingsRouteResult.success(pairing_payload(operations.list_pending))
        if action in {"pairing-approve", "pairing-deny"}:
            return self._pairing_action(
                request,
                action.removeprefix("pairing-"),
                operations,
            )
        if action == "mcp-list":
            return await self._mcp_presets(request, None, operations)
        if action.startswith("mcp-"):
            return await self._mcp_presets(
                request,
                action.removeprefix("mcp-"),
                operations,
            )
        if action == "version-check":
            return await self._version_check(operations)
        return SettingsRouteResult.failure(404, "unknown settings action")

    async def _cli_apps(
        self,
        request: SettingsRequest,
        operations: SystemSettingsOperations,
    ) -> SettingsRouteResult:
        installed_only = (query_first(request.query, "installed_only") or "").lower() in {
            "1",
            "true",
            "yes",
        }
        try:
            payload = await operations.cli_apps_payload(
                installed_only=installed_only,
                config_path=self.settings.config.path,
            )
        except Exception:
            self.logger.exception("failed to load CLI Apps payload")
            return SettingsRouteResult.failure(500, "failed to load CLI Apps")
        return SettingsRouteResult.success(payload)

    async def _cli_apps_action(
        self,
        request: SettingsRequest,
        action: str,
        operations: SystemSettingsOperations,
    ) -> SettingsRouteResult:
        try:
            payload = await asyncio.to_thread(
                operations.cli_apps_action,
                action,
                request.query,
                config_path=self.settings.config.path,
            )
        except WebUISettingsError as exc:
            return SettingsRouteResult.failure(exc.status, exc.message)
        except Exception as exc:
            status = getattr(exc, "status", 500)
            message = getattr(exc, "message", str(exc))
            if status >= 500:
                self.logger.exception("CLI Apps action '{}' failed", action)
            return SettingsRouteResult.failure(status, message)
        return SettingsRouteResult.success(payload)

    async def _features(
        self,
        operations: SystemSettingsOperations,
    ) -> SettingsRouteResult:
        try:
            payload = await asyncio.to_thread(
                operations.nanobot_features_payload,
                config_path=self.settings.config.path,
            )
        except Exception:
            self.logger.exception("failed to load nanobot features")
            return SettingsRouteResult.failure(500, "failed to load nanobot features")
        return SettingsRouteResult.success(
            self._with_channel_runtime_status(payload, operations)
        )

    def _nanobot_features_payload(
        self,
        operations: SystemSettingsOperations,
    ) -> dict[str, Any]:
        return operations.nanobot_features_payload(config_path=self.settings.config.path)

    def _nanobot_features_action(
        self,
        action: str,
        query: QueryParams,
        operations: SystemSettingsOperations,
        *,
        allow_install: bool = True,
    ) -> dict[str, Any]:
        return self.settings.mutate(
            operations.nanobot_features_action,
            action,
            query,
            allow_install=allow_install,
        )

    async def _features_action(
        self,
        request: SettingsRequest,
        action: str,
        operations: SystemSettingsOperations,
    ) -> SettingsRouteResult:
        try:
            payload = await asyncio.to_thread(
                self._nanobot_features_action,
                action,
                request.query,
                operations,
                allow_install=(
                    action != "enable"
                    or self.allow_feature_package_install(request)
                ),
            )
        except OptionalFeatureError as exc:
            return SettingsRouteResult.failure(exc.status, exc.message)
        except Exception as exc:
            status = getattr(exc, "status", 500)
            message = getattr(exc, "message", str(exc))
            if status >= 500:
                self.logger.exception(
                    "nanobot feature action '{}' failed",
                    action,
                )
            return SettingsRouteResult.failure(status, message)
        payload = await self._apply_feature_runtime_change(
            action,
            request.query,
            payload,
            operations,
        )
        payload = self._with_channel_runtime_status(payload, operations)
        return SettingsRouteResult.success(
            payload,
            decorate_restart=True,
            restart_section="runtime",
        )

    def _with_channel_runtime_status(
        self,
        payload: dict[str, Any],
        operations: SystemSettingsOperations,
    ) -> dict[str, Any]:
        if operations.channel_runtime_status is None:
            return payload
        try:
            return with_channel_runtime_status(
                payload,
                operations.channel_runtime_status(),
            )
        except Exception:
            self.logger.exception("failed to load channel runtime status")
            return payload

    async def _apply_feature_runtime_change(
        self,
        action: str,
        query: QueryParams,
        payload: dict[str, Any],
        operations: SystemSettingsOperations,
    ) -> dict[str, Any]:
        if operations.channel_feature_action is None:
            return payload
        name = (query_first(query, "name") or "").strip()
        if not name:
            return payload
        try:
            instance_id = operations.nanobot_feature_instance_target(query)
            result = operations.channel_feature_action(action, name, instance_id)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            self.logger.exception("failed to apply channel '{}' without restart", name)
            return self.feature_runtime_fallback(
                payload,
                message=(
                    f"{name} channel config was saved, but hot reload failed: {exc}"
                ),
            )

        if not isinstance(result, dict):
            return payload
        result = cast(dict[str, Any], result)
        if not result.get("handled"):
            return payload

        updated = dict(payload)
        updated["requires_restart"] = bool(result.get("requires_restart"))
        message = result.get("message")
        if isinstance(message, str) and message:
            last_action = dict(updated.get("last_action") or {})
            previous = last_action.get("message")
            last_action["message"] = (
                f"{previous}. {message}"
                if isinstance(previous, str) and previous
                else message
            )
            last_action["hot_reload"] = not updated["requires_restart"]
            if "ok" in result:
                last_action["ok"] = bool(result["ok"])
            updated["last_action"] = last_action
        return updated

    @staticmethod
    def feature_runtime_fallback(
        payload: dict[str, Any],
        *,
        message: str,
    ) -> dict[str, Any]:
        updated = dict(payload)
        updated["requires_restart"] = True
        last_action = dict(updated.get("last_action") or {})
        previous = last_action.get("message")
        last_action["message"] = (
            f"{previous}. {message}"
            if isinstance(previous, str) and previous
            else message
        )
        last_action["hot_reload"] = False
        updated["last_action"] = last_action
        return updated

    async def _channel_configure(
        self,
        request: SettingsRequest,
        operations: SystemSettingsOperations,
    ) -> SettingsRouteResult:
        name = (query_first(request.query, "name") or "").strip()
        instance_id = (
            query_first(request.query, "instance_id") or "default"
        ).strip()
        enable = (query_first(request.query, "enable") or "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        try:
            saved = await asyncio.to_thread(
                self._save_channel_config_values,
                name,
                self.parse_channel_values(request),
                instance_id,
                operations,
            )
        except WebUISettingsError as exc:
            return SettingsRouteResult.failure(exc.status, exc.message)
        except Exception:
            self.logger.exception("failed to save channel '{}' settings", name)
            return SettingsRouteResult.failure(500, "failed to save channel settings")

        payload: dict[str, Any] = {
            "name": name,
            "saved": True,
            "saved_keys": saved,
        }
        if not enable:
            features = await asyncio.to_thread(
                self._nanobot_features_payload,
                operations,
            )
            payload["nanobot_features"] = self._with_channel_runtime_status(
                features,
                operations,
            )
            return SettingsRouteResult.success(
                payload,
                decorate_restart=True,
                restart_section="runtime",
                restart_payload_key="nanobot_features",
            )

        feature_query = {"name": [name]}
        if instance_id:
            feature_query["instance_id"] = [instance_id]
        try:
            features = await asyncio.to_thread(
                self._nanobot_features_action,
                "enable",
                feature_query,
                operations,
                allow_install=self.allow_feature_package_install(request),
            )
        except OptionalFeatureError as exc:
            return SettingsRouteResult.failure(
                exc.status,
                f"Settings saved, but {exc.message}",
            )
        except Exception as exc:
            self.logger.exception(
                "failed to enable channel '{}' after settings save",
                name,
            )
            return SettingsRouteResult.failure(
                500,
                f"Settings saved, but enabling {name} failed: {exc}",
            )

        features = await self._apply_feature_runtime_change(
            "enable",
            feature_query,
            features,
            operations,
        )
        payload["nanobot_features"] = self._with_channel_runtime_status(
            features,
            operations,
        )
        return SettingsRouteResult.success(
            payload,
            decorate_restart=True,
            restart_section="runtime",
            restart_payload_key="nanobot_features",
        )

    async def _channel_validate(
        self,
        request: SettingsRequest,
        operations: SystemSettingsOperations,
    ) -> SettingsRouteResult:
        name = (query_first(request.query, "name") or "").strip()
        instance_id = (
            query_first(request.query, "instance_id") or "default"
        ).strip()
        try:
            payload = await asyncio.to_thread(
                operations.validate_channel_config,
                name,
                self.parse_channel_values(request),
                instance_id=instance_id,
            )
        except WebUISettingsError as exc:
            return SettingsRouteResult.failure(exc.status, exc.message)
        except Exception:
            self.logger.exception("failed to validate channel '{}' settings", name)
            return SettingsRouteResult.failure(
                500,
                "failed to validate channel settings",
            )
        return SettingsRouteResult.success(payload)

    @staticmethod
    def parse_channel_values(request: SettingsRequest) -> dict[str, Any]:
        if request.payload is None or "values" not in request.payload:
            return {}
        values = request.payload.get("values")
        if not isinstance(values, dict):
            raise WebUISettingsError(
                "channel settings payload must be a JSON object"
            )
        return cast(dict[str, Any], values)

    def _save_channel_config_values(
        self,
        name: str,
        raw_values: dict[str, Any],
        instance_id: str,
        operations: SystemSettingsOperations,
    ) -> list[str]:
        return self.settings.config.update(
            lambda config: save_channel_config_values(
                config,
                name,
                raw_values,
                instance_id,
                load_channel_plugin=operations.load_channel_plugin,
            )
        )

    async def _channel_connect(
        self,
        request: SettingsRequest,
        channel_name: str,
        action: str,
        operations: SystemSettingsOperations,
    ) -> SettingsRouteResult:
        try:
            connector = self._channel_connectors.get(channel_name)
            if connector is None:
                plugin = operations.load_channel_plugin(channel_name)
                connector = plugin.load_connector()
                self._channel_connectors[channel_name] = connector
        except ImportError:
            return SettingsRouteResult.failure(
                404,
                f"channel '{channel_name}' does not support connect",
            )

        try:
            payload = await connector.handle(action, request.query)
        except ChannelConnectError as exc:
            return SettingsRouteResult.failure(exc.status, exc.message)
        except Exception:
            self.logger.exception(
                "failed to run {} WebUI connect action for {}",
                action,
                channel_name,
            )
            return SettingsRouteResult.failure(
                500,
                f"failed to {action} {channel_name} connection",
            )

        if payload.get("status") != "succeeded":
            return SettingsRouteResult.success(payload)
        payload = await self._with_channel_connect_success(
            request,
            channel_name,
            payload,
            operations,
        )
        return SettingsRouteResult.success(
            payload,
            decorate_restart=True,
            restart_section="runtime",
            restart_payload_key="nanobot_features",
        )

    async def _with_channel_connect_success(
        self,
        request: SettingsRequest,
        channel_name: str,
        payload: dict[str, Any],
        operations: SystemSettingsOperations,
    ) -> dict[str, Any]:
        target = {"name": [channel_name]}
        if payload.get("instance_id"):
            target["instance_id"] = [str(payload["instance_id"])]
        try:
            features = await asyncio.to_thread(
                self._nanobot_features_action,
                "enable",
                target,
                operations,
                allow_install=self.allow_feature_package_install(request),
            )
        except OptionalFeatureError as exc:
            features = self.feature_runtime_fallback(
                self._nanobot_features_payload(operations),
                message=(
                    f"{channel_name} connected, but enabling channel support failed: "
                    f"{exc.message}"
                ),
            )
        else:
            features = await self._apply_feature_runtime_change(
                "enable",
                target,
                features,
                operations,
            )
        updated = dict(payload)
        updated["nanobot_features"] = self._with_channel_runtime_status(
            features,
            operations,
        )
        return updated

    def allow_feature_package_install(self, request: SettingsRequest) -> bool:
        if request.local_browser:
            return True
        try:
            return bool(
                self.settings.config.load().tools.webui_allow_remote_package_install
            )
        except Exception:
            self.logger.exception("failed to load remote package install policy")
            return False

    def _pairing_action(
        self,
        request: SettingsRequest,
        action: str,
        operations: SystemSettingsOperations,
    ) -> SettingsRouteResult:
        code = (query_first(request.query, "code") or "").strip()
        if not code:
            return SettingsRouteResult.failure(400, "Missing pairing code")
        if action == "approve":
            result = operations.approve_code(code)
            if result is None:
                return SettingsRouteResult.failure(
                    404,
                    "Pairing code not found or expired",
                )
            channel, sender_id = result
            return SettingsRouteResult.success(
                pairing_payload(
                    operations.list_pending,
                    {
                        "ok": True,
                        "action": "approve",
                        "message": f"Approved {sender_id} for {channel}",
                        "channel": channel,
                        "sender_id": sender_id,
                        "code": code,
                    },
                )
            )

        if not operations.deny_code(code):
            return SettingsRouteResult.failure(
                404,
                "Pairing code not found or expired",
            )
        return SettingsRouteResult.success(
            pairing_payload(
                operations.list_pending,
                {
                    "ok": True,
                    "action": "deny",
                    "message": f"Denied pairing code {code}",
                    "code": code,
                },
            )
        )

    async def _mcp_presets(
        self,
        request: SettingsRequest,
        action: str | None,
        operations: SystemSettingsOperations,
    ) -> SettingsRouteResult:
        try:
            payload = await operations.mcp_presets_action(
                action,
                request.query,
                reload_mcp=operations.reload_mcp,
                mcp_runtime_status=operations.mcp_runtime_status,
                config=self.settings.config,
            )
        except Exception as exc:
            status = getattr(exc, "status", 500)
            message = getattr(exc, "message", str(exc))
            if status >= 500:
                self.logger.exception(
                    "MCP preset action '{}' failed",
                    action or "list",
                )
            return SettingsRouteResult.failure(status, message)
        return SettingsRouteResult.success(
            payload,
            decorate_restart=action is not None,
            restart_section="runtime" if action is not None else None,
        )

    async def _version_check(
        self,
        operations: SystemSettingsOperations,
    ) -> SettingsRouteResult:
        try:
            update_info = await asyncio.to_thread(operations.check_for_update)
        except Exception:
            self.logger.exception("version check failed")
            return SettingsRouteResult.failure(500, "version check failed")
        return SettingsRouteResult.success({"updateAvailable": update_info})
