"""Best-effort channel setup validation shared by management surfaces.

Validation is intentionally non-authoritative: it helps the UI explain whether a
channel looks ready, but it never writes config and it does not replace runtime
channel startup semantics.
"""

from __future__ import annotations

import re
import socket
import ssl
from datetime import UTC, datetime
from typing import Any

import httpx

from nanobot.channels._setup import channel_setup_spec
from nanobot.channels.contracts import (
    ChannelSetupSpec,
    ChannelValidationContext,
    channel_field_value,
    channel_instance_config,
    channel_value_present,
)
from nanobot.channels.plugin import ChannelPlugin
from nanobot.channels.registry import load_channel_plugin
from nanobot.config.loader import load_config
from nanobot.security.network import resolve_url_target

CheckStatus = str
SetupStatus = str

_TIMEOUT_SECONDS = 4.0


def _official_action(name: str) -> str | None:
    _, spec = _channel_contract(name)
    return spec.official_url if spec is not None else None


def _channel_contract(
    name: str,
) -> tuple[ChannelPlugin | None, ChannelSetupSpec | None]:
    try:
        plugin = load_channel_plugin(name)
    except ImportError:
        return None, None
    return plugin, channel_setup_spec(name, plugin=plugin)


def validate_channel_config(
    name: str,
    raw_values: dict[str, Any] | None = None,
    *,
    instance_id: str = "default",
) -> dict[str, Any]:
    """Validate a channel setup without mutating persisted config."""

    channel = (name or "").strip()
    if not channel:
        return _payload("unknown", "unsupported", [_check("channel", "Channel", "fail", "Missing channel name")])

    config = load_config()
    section = getattr(config.channels, channel, None)
    plugin, setup_spec = _channel_contract(channel)
    values = _channel_config(
        section,
        plugin=plugin,
        instance_id=instance_id,
    )
    values = _merge_form_values(channel, values, raw_values or {}, setup_spec=setup_spec)

    if setup_spec is not None and setup_spec.validator is not None:
        context = ChannelValidationContext(
            allow_local_service_access=config.tools.webui_allow_local_service_access,
        )
        custom_payload = setup_spec.validator(values, context)
        if custom_payload is not None:
            payload = dict(custom_payload)
            payload.setdefault("checks", [])
            payload.setdefault("missing_fields", [])
            payload.setdefault("can_enable", payload.get("status") in {"configured", "connected"})
            payload.setdefault("requires_restart", True)
            payload["name"] = channel
            return payload

    payload = _validate_generic(channel, values)
    payload["name"] = channel
    return payload


def _validate_generic(name: str, values: dict[str, Any]) -> dict[str, Any]:
    _, spec = _channel_contract(name)
    checks, missing = _required_checks(name, values, setup_spec=spec)
    if spec is not None:
        composite_checks, composite_missing = _composite_requirement_checks(spec, values)
        checks.extend(composite_checks)
        missing.extend(composite_missing)
    if spec is not None and spec.required:
        checks.append(_check("manual_review", "Manual setup", "skipped", "This channel can be checked from saved fields, but not fully verified in-browser."))
        return _status_from_checks(name, checks, list(dict.fromkeys(missing)))
    if _enabled(values):
        return _payload(name, "configured", [_check("enabled", "Enabled", "pass", "This channel is enabled.")])
    return _payload(name, "unsupported", [_check("support", "WebUI setup", "skipped", "This channel is not configurable from the WebUI yet.")])


def _channel_config(
    section: Any,
    *,
    plugin: ChannelPlugin | None,
    instance_id: str,
) -> dict[str, Any]:
    if plugin is not None:
        return channel_instance_config(plugin, section, instance_id=instance_id)
    if hasattr(section, "model_dump"):
        return dict(section.model_dump(mode="json", by_alias=True))
    if isinstance(section, dict):
        return dict(section)
    return {}


def _merge_form_values(
    name: str,
    values: dict[str, Any],
    raw_values: dict[str, Any],
    *,
    setup_spec: ChannelSetupSpec | None = None,
) -> dict[str, Any]:
    merged = dict(values)
    prefix = f"channels.{name}."
    spec = setup_spec
    secrets = spec.secrets if spec is not None else frozenset()
    for raw_key, raw_value in raw_values.items():
        if not isinstance(raw_key, str) or not raw_key:
            continue
        field = raw_key[len(prefix):] if raw_key.startswith(prefix) else raw_key
        if field in secrets and not _str(raw_value):
            continue
        _assign(merged, field, raw_value)
    return merged


def _required_checks(
    name: str,
    values: dict[str, Any],
    *,
    setup_spec: ChannelSetupSpec | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    missing: list[str] = []
    spec = setup_spec
    if spec is None:
        _, spec = _channel_contract(name)
    for field in spec.simple_required_fields if spec is not None else ():
        value = _get(values, field)
        if field == "consentGranted":
            if not _truthy(value):
                missing.append(field)
            continue
        if _str(value):
            checks.append(_check(f"field:{field}", _label(field), "pass", "Configured."))
        else:
            missing.append(field)
            checks.append(_check(f"field:{field}", _label(field), "fail", "Required."))
    return checks, missing


def _composite_requirement_checks(
    setup_spec: ChannelSetupSpec,
    values: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    missing: list[str] = []
    for index, requirement in enumerate(setup_spec.required):
        if requirement.simple_field is not None or requirement.is_satisfied(values):
            continue

        alternatives = [
            (
                alternative,
                tuple(
                    field
                    for field in alternative
                    if not channel_value_present(channel_field_value(values, field))
                ),
            )
            for alternative in requirement.alternatives
        ]
        closest = min(
            alternatives,
            key=lambda candidate: (
                len(candidate[1]),
                -(len(candidate[0]) - len(candidate[1])),
            ),
            default=((), ()),
        )[1]
        missing.extend(closest or (f"required_setup_{index}",))
        alternatives_label = " or ".join(
            " + ".join(_label(field) for field in alternative)
            for alternative in requirement.alternatives
        )
        message = (
            f"Complete one of: {alternatives_label}."
            if alternatives_label
            else "Required setup is incomplete."
        )
        checks.append(
            _check(
                f"requirement:{index}",
                "Required setup",
                "fail",
                message,
            )
        )
    return checks, missing


def _status_from_checks(
    name: str,
    checks: list[dict[str, Any]],
    missing: list[str],
    *,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if missing:
        return _payload(name, "needs_setup", checks, identity=identity, missing_fields=missing, can_enable=False)
    if any(check["status"] == "fail" for check in checks):
        return _payload(name, "invalid", checks, identity=identity, missing_fields=missing, can_enable=False)
    if any(check["status"] == "warn" for check in checks) or any(check["status"] == "skipped" for check in checks):
        return _payload(name, "configured", checks, identity=identity, missing_fields=missing)
    return _payload(name, "connected", checks, identity=identity, missing_fields=missing)


def _payload(
    name: str,
    status: SetupStatus,
    checks: list[dict[str, Any]],
    *,
    identity: dict[str, Any] | None = None,
    missing_fields: list[str] | None = None,
    can_enable: bool | None = None,
) -> dict[str, Any]:
    missing = missing_fields or []
    return {
        "name": name,
        "status": status,
        "checks": checks,
        "identity": {key: value for key, value in (identity or {}).items() if value},
        "missing_fields": missing,
        "can_enable": status not in {"needs_setup", "invalid", "unsupported"} and not missing
        if can_enable is None
        else can_enable,
        "requires_restart": False,
        "checked_at": datetime.now(UTC).isoformat(),
        "message": _status_message(status),
    }


def _check(
    check_id: str,
    label: str,
    status: CheckStatus,
    message: str | None = None,
    *,
    action_url: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"id": check_id, "label": label, "status": status}
    if message:
        payload["message"] = message
    if action_url:
        payload["action_url"] = action_url
    return payload


def _assign(values: dict[str, Any], field: str, value: Any) -> None:
    target = values
    parts = field.split(".")
    for part in parts[:-1]:
        current = target.get(part)
        if not isinstance(current, dict):
            current = {}
            target[part] = current
        target = current
    target[parts[-1]] = value


def _get(values: dict[str, Any], field: str) -> Any:
    target: Any = values
    for part in field.split("."):
        if not isinstance(target, dict):
            return None
        target = target.get(part)
    return target


def _str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _str(value).lower() in {"1", "true", "yes", "on", "granted"}


def _enabled(values: dict[str, Any]) -> bool:
    return _truthy(values.get("enabled"))


def _label(field: str) -> str:
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", field).replace(".", " ").replace("_", " ")
    return words[:1].upper() + words[1:]


def _status_message(status: str) -> str:
    return {
        "connected": "Connection verified.",
        "configured": "Configuration is present, but full verification was not possible.",
        "needs_setup": "Required setup is missing.",
        "invalid": "Configuration was checked and looks invalid.",
        "unsupported": "This channel is not supported by the WebUI setup checker.",
    }.get(status, "Channel checked.")


def _message_from_response(data: dict[str, Any], fallback: str) -> str:
    error = data.get("error") or data.get("description") or data.get("message")
    return str(error) if error else fallback


def _http_get(url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
    return data if isinstance(data, dict) else {}


def _http_post(url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        response = client.post(url, headers=headers)
        response.raise_for_status()
        data = response.json()
    return data if isinstance(data, dict) else {}


def _probe_tcp(host: str, port: int, *, allow_loopback: bool = False) -> None:
    url_host = host if ":" not in host or host.startswith("[") else f"[{host}]"
    ok, error, resolved_ips = resolve_url_target(
        f"http://{url_host}:{port}/",
        allow_loopback=allow_loopback,
    )
    if not ok:
        raise ValueError(error)

    context = ssl.create_default_context()
    last_error: OSError | None = None
    for target_ip in resolved_ips:
        try:
            with socket.create_connection((target_ip, port), timeout=_TIMEOUT_SECONDS) as sock:
                if port in {465, 993, 995}:
                    with context.wrap_socket(sock, server_hostname=host.strip("[]")):
                        return
                return
        except OSError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise OSError(f"Could not resolve {host}")


# Public helpers for channel-owned validators. Keeping response shaping here lets
# each package own its platform checks without depending on WebUI implementation
# modules.
check = _check
enabled = _enabled
http_get = _http_get
http_post = _http_post
int_value = _int
message_from_response = _message_from_response
official_action = _official_action
payload = _payload
probe_tcp = _probe_tcp
required_checks = _required_checks
status_from_checks = _status_from_checks
string_value = _str
truthy = _truthy

__all__ = [
    "check",
    "enabled",
    "http_get",
    "http_post",
    "int_value",
    "message_from_response",
    "official_action",
    "payload",
    "probe_tcp",
    "required_checks",
    "status_from_checks",
    "string_value",
    "truthy",
    "validate_channel_config",
]
