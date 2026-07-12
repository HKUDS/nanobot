"""Best-effort Channel setup validation for the WebUI.

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

from nanobot.config.loader import load_config
from nanobot.security.network import resolve_url_target
from nanobot.webui.channel_setup import channel_setup_spec

CheckStatus = str
SetupStatus = str

_TIMEOUT_SECONDS = 4.0


def _official_action(name: str) -> str | None:
    spec = channel_setup_spec(name)
    return spec.official_url if spec is not None else None


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
    values = _channel_config(channel, section, instance_id=instance_id)
    values = _merge_form_values(channel, values, raw_values or {})

    validator = _VALIDATORS.get(channel, _validate_generic)
    if channel == "email":
        payload = _validate_email(
            channel,
            values,
            allow_loopback=config.tools.webui_allow_local_service_access,
        )
    else:
        payload = validator(channel, values)
    payload["name"] = channel
    return payload


def _validate_websocket(name: str, values: dict[str, Any]) -> dict[str, Any]:
    checks = [
        _check(
            "managed",
            "Managed by WebUI",
            "pass",
            "The browser workbench prepares the local WebSocket channel.",
            action_url=_official_action(name),
        )
    ]
    return _payload(name, "connected" if _enabled(values) else "configured", checks, can_enable=True)


def _validate_telegram(name: str, values: dict[str, Any]) -> dict[str, Any]:
    checks, missing = _required_checks(name, values)
    token = _str(values.get("token"))
    if token:
        if not re.match(r"^\d+:[A-Za-z0-9_-]{20,}$", token):
            checks.append(_check("token_format", "Token format", "fail", "Telegram tokens look like 123456:ABC..."))
        else:
            checks.append(_check("token_format", "Token format", "pass", "Looks like a BotFather token."))
            try:
                data = _http_get(f"https://api.telegram.org/bot{token}/getMe")
                if data.get("ok") and isinstance(data.get("result"), dict):
                    bot = data["result"]
                    identity = {
                        "name": bot.get("username") or bot.get("first_name"),
                        "account": str(bot.get("id") or ""),
                    }
                    checks.append(_check("get_me", "Bot identity", "pass", "Telegram accepted the bot token."))
                    return _payload(name, "connected", checks, identity=identity, missing_fields=missing)
                checks.append(_check("get_me", "Bot identity", "fail", _message_from_response(data, "Telegram rejected the token.")))
            except Exception as exc:
                checks.append(_check("get_me", "Bot identity", "warn", f"Could not reach Telegram now: {exc}"))
    return _status_from_checks(name, checks, missing)


def _validate_discord(name: str, values: dict[str, Any]) -> dict[str, Any]:
    checks, missing = _required_checks(name, values)
    token = _str(values.get("token"))
    if token:
        try:
            data = _http_get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {token}"},
            )
            bot_id = str(data.get("id") or "")
            checks.append(_check("bot_token", "Bot token", "pass", "Discord accepted the bot token."))
            identity = {
                "name": data.get("global_name") or data.get("username"),
                "account": bot_id,
            }
            if bot_id:
                checks.append(
                    _check(
                        "invite",
                        "Server invite",
                        "pass",
                        "Use this generated OAuth URL to invite the bot.",
                        action_url=(
                            "https://discord.com/oauth2/authorize"
                            f"?client_id={bot_id}&scope=bot%20applications.commands"
                        ),
                    )
                )
            return _payload(name, "connected", checks, identity=identity, missing_fields=missing)
        except httpx.HTTPStatusError as exc:
            checks.append(_check("bot_token", "Bot token", "fail", f"Discord rejected the token: HTTP {exc.response.status_code}"))
        except Exception as exc:
            checks.append(_check("bot_token", "Bot token", "warn", f"Could not reach Discord now: {exc}"))
    return _status_from_checks(name, checks, missing)


def _validate_slack(name: str, values: dict[str, Any]) -> dict[str, Any]:
    checks, missing = _required_checks(name, values)
    app_token = _str(values.get("appToken"))
    bot_token = _str(values.get("botToken"))
    if app_token:
        checks.append(
            _check(
                "app_token_prefix",
                "Socket Mode app token",
                "pass" if app_token.startswith("xapp-") else "fail",
                "App-level Socket Mode tokens start with xapp-.",
                action_url=_official_action(name),
            )
        )
    if bot_token:
        checks.append(
            _check(
                "bot_token_prefix",
                "Bot token",
                "pass" if bot_token.startswith("xoxb-") else "fail",
                "Bot tokens start with xoxb- after installing the Slack app.",
                action_url=_official_action(name),
            )
        )
        if bot_token.startswith("xoxb-"):
            try:
                data = _http_post(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {bot_token}"},
                )
                if data.get("ok"):
                    identity = {
                        "name": data.get("user"),
                        "workspace": data.get("team"),
                        "account": data.get("user_id"),
                    }
                    checks.append(_check("auth_test", "Workspace identity", "pass", "Slack accepted the bot token."))
                    status = "connected" if app_token.startswith("xapp-") else "configured"
                    return _payload(name, status, checks, identity=identity, missing_fields=missing)
                checks.append(_check("auth_test", "Workspace identity", "fail", _message_from_response(data, "Slack rejected the bot token.")))
            except Exception as exc:
                checks.append(_check("auth_test", "Workspace identity", "warn", f"Could not reach Slack now: {exc}"))
    return _status_from_checks(name, checks, missing)


def _validate_email(
    name: str,
    values: dict[str, Any],
    *,
    allow_loopback: bool = False,
) -> dict[str, Any]:
    checks, missing = _required_checks(name, values)
    if _truthy(values.get("consentGranted")):
        checks.append(_check("consent", "Mailbox consent", "pass", "Consent is enabled for this mailbox."))
    else:
        checks.append(_check("consent", "Mailbox consent", "fail", "Grant consent before nanobot reads this mailbox."))

    for prefix, default_port in (("imap", 993), ("smtp", 587)):
        host = _str(values.get(f"{prefix}Host"))
        port = _int(values.get(f"{prefix}Port")) or default_port
        if not host:
            continue
        if port <= 0 or port > 65535:
            checks.append(_check(f"{prefix}_port", f"{prefix.upper()} port", "fail", "Port must be between 1 and 65535."))
            continue
        checks.append(_check(f"{prefix}_settings", f"{prefix.upper()} settings", "pass", f"{host}:{port} is set."))
        try:
            _probe_tcp(host, port, allow_loopback=allow_loopback)
            checks.append(_check(f"{prefix}_reachability", f"{prefix.upper()} reachability", "pass", "The server accepted a TCP connection."))
        except Exception as exc:
            checks.append(_check(f"{prefix}_reachability", f"{prefix.upper()} reachability", "warn", f"Could not verify network reachability now: {exc}"))

    identity = {"account": _str(values.get("fromAddress") or values.get("imapUsername") or values.get("smtpUsername"))}
    return _status_from_checks(name, checks, missing, identity=identity)


def _validate_feishu(name: str, values: dict[str, Any]) -> dict[str, Any]:
    checks, missing = _required_checks(name, values)
    display_name = _str(values.get("displayName") or values.get("name"))
    avatar_url = _str(values.get("avatarUrl"))
    if _str(values.get("appId")).startswith(("cli_", "oapi_")):
        checks.append(_check("app_id", "App ID", "pass", "A Feishu/Lark App ID is saved."))
    elif _str(values.get("appId")):
        checks.append(_check("app_id", "App ID", "warn", "App ID is saved, but it does not look like a standard Feishu App ID."))
    status = "connected" if not missing else "needs_setup"
    identity = {
        "name": display_name or "Feishu assistant",
        "avatar_url": avatar_url or None,
        "account": _str(values.get("appId")),
    }
    return _payload(name, status, checks, identity=identity, missing_fields=missing)


def _validate_matrix(name: str, values: dict[str, Any]) -> dict[str, Any]:
    checks, missing = _required_checks(name, values)
    password = _str(values.get("password"))
    access_token = _str(values.get("accessToken"))
    device_id = _str(values.get("deviceId"))

    if password:
        checks.append(_check("login", "Login credentials", "pass", "Password login is configured."))
    elif access_token and device_id:
        checks.append(
            _check(
                "login",
                "Login credentials",
                "pass",
                "Access token login is configured with its device ID.",
            )
        )
    else:
        if not password and not access_token:
            missing.append("password_or_accessToken")
            message = "Add a password, or an access token with its device ID."
        else:
            missing.append("deviceId")
            message = "A device ID is required with an access token."
        checks.append(_check("login", "Login credentials", "fail", message))

    checks.append(
        _check(
            "manual_review",
            "Matrix account",
            "skipped",
            "Room access is verified when the channel starts.",
        )
    )
    return _status_from_checks(name, checks, list(dict.fromkeys(missing)))


def _validate_cli_handoff(name: str, values: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    if _enabled(values) or _str(values.get("token")) or _str(values.get("databasePath")):
        checks.append(_check("local_state", "Local login state", "pass", "Saved local login state was detected."))
        return _payload(name, "configured", checks, can_enable=True)
    checks.append(
        _check(
            "terminal_login",
            "Terminal login",
            "skipped",
            "This channel uses a terminal QR login flow.",
            action_url=_official_action(name),
        )
    )
    return _payload(name, "needs_setup", checks, missing_fields=["terminal_login"], can_enable=False)


def _validate_generic(name: str, values: dict[str, Any]) -> dict[str, Any]:
    checks, missing = _required_checks(name, values)
    spec = channel_setup_spec(name)
    if spec is not None and spec.required:
        checks.append(_check("manual_review", "Manual setup", "skipped", "This channel can be checked from saved fields, but not fully verified in-browser."))
        return _status_from_checks(name, checks, missing)
    if _enabled(values):
        return _payload(name, "configured", [_check("enabled", "Enabled", "pass", "This channel is enabled.")])
    return _payload(name, "unsupported", [_check("support", "WebUI setup", "skipped", "This channel is not configurable from the WebUI yet.")])


_VALIDATORS = {
    "websocket": _validate_websocket,
    "telegram": _validate_telegram,
    "discord": _validate_discord,
    "slack": _validate_slack,
    "email": _validate_email,
    "feishu": _validate_feishu,
    "matrix": _validate_matrix,
    "whatsapp": _validate_cli_handoff,
    "weixin": _validate_cli_handoff,
}


def _channel_config(name: str, section: Any, *, instance_id: str) -> dict[str, Any]:
    if name == "feishu":
        try:
            from nanobot.channels._feishu_instances import feishu_instance_specs
            from nanobot.channels.feishu import FeishuChannel

            specs = feishu_instance_specs(section, FeishuChannel.default_config())
            selected = next((spec for spec in specs if spec.instance_id == instance_id), None)
            return dict(selected.config) if selected is not None else {}
        except Exception:
            return {}
    if hasattr(section, "model_dump"):
        return dict(section.model_dump(mode="json", by_alias=True))
    if isinstance(section, dict):
        return dict(section)
    return {}


def _merge_form_values(
    name: str,
    values: dict[str, Any],
    raw_values: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(values)
    prefix = f"channels.{name}."
    spec = channel_setup_spec(name)
    secrets = spec.secrets if spec is not None else frozenset()
    for raw_key, raw_value in raw_values.items():
        if not isinstance(raw_key, str) or not raw_key:
            continue
        field = raw_key[len(prefix):] if raw_key.startswith(prefix) else raw_key
        if field in secrets and not _str(raw_value):
            continue
        _assign(merged, field, raw_value)
    return merged


def _required_checks(name: str, values: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    missing: list[str] = []
    spec = channel_setup_spec(name)
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
