"""Read channel CLI state and export runtime env values."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SERVICE_NAME = "lark-cli"
SAFE_FILE_RE = re.compile(r"[^a-zA-Z0-9._-]")
REFRESH_AHEAD_MS = 5 * 60 * 1000


def looks_like_masked_secret(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text in {"********", "........"}:
        return True
    return len(text) >= 6 and len(set(text)) == 1 and text[0] in {"*", "."}


def safe_file_name(account: str) -> str:
    return SAFE_FILE_RE.sub("_", account) + ".enc"


def config_dir() -> Path:
    raw = os.environ.get("LARKSUITE_CLI_CONFIG_DIR")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".lark-cli"


def data_dir() -> Path:
    raw = os.environ.get("LARKSUITE_CLI_DATA_DIR")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".local" / "share"


def storage_dir() -> Path:
    return data_dir() / SERVICE_NAME


def dingtalk_config_dir() -> Path:
    raw = os.environ.get("DWS_CONFIG_DIR")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".dws"


def load_multi_config() -> dict[str, Any]:
    path = config_dir() / "config.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def current_or_named_profile(config: dict[str, Any], profile_name: str | None) -> dict[str, Any] | None:
    apps = config.get("apps") or []
    if not isinstance(apps, list):
        return None

    if profile_name:
        for app in apps:
            if not isinstance(app, dict):
                continue
            name = str(app.get("name") or "")
            app_id = str(app.get("appId") or "")
            if profile_name in {name, app_id}:
                return app
        return None

    current = str(config.get("currentApp") or "")
    if current:
        for app in apps:
            if not isinstance(app, dict):
                continue
            name = str(app.get("name") or "")
            app_id = str(app.get("appId") or "")
            if current in {name, app_id}:
                return app
    for app in apps:
        if isinstance(app, dict):
            return app
    return None


def read_master_key() -> bytes | None:
    path = storage_dir() / "master.key"
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    if len(data) != 32:
        return None
    return data


def decrypt_storage_value(account_key: str) -> str:
    master_key = read_master_key()
    if not master_key:
        return ""
    path = storage_dir() / safe_file_name(account_key)
    try:
        encrypted = path.read_bytes()
    except FileNotFoundError:
        return ""
    if len(encrypted) < 12 + 16:
        return ""
    nonce = encrypted[:12]
    ciphertext = encrypted[12:]
    try:
        plain = AESGCM(master_key).decrypt(nonce, ciphertext, None)
    except Exception:
        return ""
    return plain.decode("utf-8", errors="replace")


def resolve_secret(app: dict[str, Any]) -> str:
    secret = app.get("appSecret")
    if isinstance(secret, str):
        return "" if looks_like_masked_secret(secret) else secret
    if isinstance(secret, dict):
        source = str(secret.get("source") or "")
        ref_id = str(secret.get("id") or "")
        if source == "keychain" and ref_id:
            resolved = decrypt_storage_value(ref_id)
            return "" if looks_like_masked_secret(resolved) else resolved
        if source == "file" and ref_id:
            try:
                resolved = Path(ref_id).read_text(encoding="utf-8").strip()
                return "" if looks_like_masked_secret(resolved) else resolved
            except Exception:
                return ""
    return ""


def token_status(token: dict[str, Any]) -> str:
    now = int(time.time() * 1000)
    expires_at = int(token.get("expiresAt") or 0)
    refresh_expires_at = int(token.get("refreshExpiresAt") or 0)
    if now < expires_at - REFRESH_AHEAD_MS:
        return "valid"
    if now < refresh_expires_at:
        return "needs_refresh"
    return "expired"


def read_user_token(app_id: str, user_open_id: str) -> dict[str, Any]:
    if not app_id or not user_open_id:
        return {}
    raw = decrypt_storage_value(f"{app_id}:{user_open_id}")
    if not raw:
        return {}
    try:
        token = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(token, dict):
        return {}
    token["tokenStatus"] = token_status(token)
    return token


def resolve_authorized_user(app_id: str, users: list[Any]) -> tuple[str, str, dict[str, Any]]:
    normalized_users = [item for item in users if isinstance(item, dict)]
    fallback_user_open_id = ""
    fallback_user_name = ""
    fallback_token: dict[str, Any] = {}

    for user in normalized_users:
        user_open_id = str(user.get("userOpenId") or "").strip()
        user_name = str(user.get("userName") or "").strip()
        if not fallback_user_open_id:
            fallback_user_open_id = user_open_id
            fallback_user_name = user_name
        token = read_user_token(app_id, user_open_id)
        if token and str(token.get("tokenStatus") or "") in {"valid", "needs_refresh"}:
            return user_open_id, user_name, token
        if token and not fallback_token:
            fallback_token = token
            fallback_user_open_id = user_open_id
            fallback_user_name = user_name

    return fallback_user_open_id, fallback_user_name, fallback_token


def build_feishu_status(provider: str, profile_name: str | None) -> dict[str, Any]:
    state = {
        "provider": provider,
        "profile": profile_name or "",
        "brand": "feishu",
        "app_id": "",
        "configured": False,
        "env_ready": False,
        "authorized": False,
        "user_name": "",
        "user_open_id": "",
        "token_status": "",
        "scope": "",
        "error": "",
    }

    config = load_multi_config()
    app = current_or_named_profile(config, profile_name)
    if not app:
        if profile_name:
            state["profile"] = profile_name
            state["error"] = "profile_not_found"
        return state

    app_id = str(app.get("appId") or "").strip()
    secret = resolve_secret(app).strip()
    users = app.get("users") or []
    user_open_id, user_name, token = resolve_authorized_user(app_id, users if isinstance(users, list) else [])
    token_status_value = str(token.get("tokenStatus") or "")
    configured = bool(app_id and app.get("appSecret"))
    env_ready = bool(app_id and secret)
    authorized = bool(env_ready and user_open_id and token and token_status_value in {"valid", "needs_refresh"})

    state.update(
        {
            "profile": str(app.get("name") or app_id),
            "brand": str(app.get("brand") or "feishu"),
            "app_id": app_id,
            "configured": configured,
            "env_ready": env_ready,
            "user_name": user_name,
            "user_open_id": user_open_id,
            "token_status": token_status_value,
            "scope": str(token.get("scope") or ""),
            "authorized": authorized,
        }
    )

    if configured and not env_ready:
        state["error"] = "app_secret_unavailable"
    return state


def parse_json_output(raw_output: str) -> dict[str, Any]:
    text = (raw_output or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        return data
    for line in reversed([item.strip() for item in text.splitlines() if item.strip()]):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def build_dingtalk_status(provider: str) -> dict[str, Any]:
    app_config = load_json_file(dingtalk_config_dir() / "app.json")
    app_id = str(app_config.get("clientId") or "").strip()
    state = {
        "provider": provider,
        "profile": "",
        "app_id": app_id,
        "configured": bool(app_id),
        "authenticated": False,
        "authorized": False,
        "corp_id": "",
        "corp_name": "",
        "user_id": "",
        "user_name": "",
        "message": "未登录",
        "error": "",
    }

    if not shutil.which("dws"):
        state["error"] = "dws_not_installed"
        state["message"] = "dws 不存在"
        return state

    env = dict(os.environ)
    env["DWS_CONFIG_DIR"] = str(dingtalk_config_dir())
    try:
        result = subprocess.run(
            ["dws", "auth", "status", "-f", "json"],
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
            check=False,
        )
    except Exception as exc:
        state["error"] = f"status_command_failed:{exc}"
        state["message"] = str(exc)
        return state

    payload = parse_json_output(result.stdout)
    if not payload:
        state["error"] = "status_parse_failed"
        state["message"] = (result.stderr or result.stdout or "读取 dws 状态失败").strip()
        return state

    authenticated = bool(payload.get("authenticated"))
    state.update(
        {
            "authenticated": authenticated,
            "authorized": authenticated,
            "corp_id": str(payload.get("corp_id") or ""),
            "corp_name": str(payload.get("corp_name") or ""),
            "user_id": str(payload.get("user_id") or ""),
            "user_name": str(payload.get("user_name") or ""),
            "message": str(payload.get("message") or ("已登录" if authenticated else "未登录")),
            "error": "",
        }
    )
    return state


def build_status(provider: str, profile_name: str | None) -> dict[str, Any]:
    normalized = str(provider or "feishu").strip().lower()
    if normalized == "dingtalk":
        return build_dingtalk_status(normalized)
    return build_feishu_status(normalized, profile_name)


def print_env_exports(provider: str, profile_name: str | None) -> int:
    if str(provider or "").strip().lower() == "dingtalk":
        return 0
    state = build_status(provider, profile_name)
    secret = ""
    if state["env_ready"]:
        config = load_multi_config()
        app = current_or_named_profile(config, profile_name)
        if isinstance(app, dict):
            secret = resolve_secret(app).strip()

    exports = {
        "NANOBOT_CHANNELS__FEISHU__APP_ID": state["app_id"] if state["env_ready"] else "",
        "NANOBOT_CHANNELS__FEISHU__APP_SECRET": secret if state["env_ready"] else "",
    }
    for key, value in exports.items():
        print(f"export {key}={shlex.quote(value)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read lark-cli channel state")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("status", "env"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--provider", default="feishu")
        sub.add_argument("--profile", default="")

    args = parser.parse_args(argv)

    if args.command == "status":
        print(json.dumps(build_status(args.provider, args.profile or None), ensure_ascii=False))
        return 0
    return print_env_exports(args.provider, args.profile or None)


if __name__ == "__main__":
    sys.exit(main())
