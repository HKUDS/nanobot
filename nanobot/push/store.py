"""Device token storage for push notifications.

Stores registered device tokens in a JSON file under the workspace.
Each user (identified by gateway token hash) can have multiple devices.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from loguru import logger


class DeviceStore:
    """Thread-safe JSON file store for device push tokens.

    Structure:
    {
        "<token_hash>": {
            "devices": {
                "<device_id>": {
                    "fcm_token": "...",
                    "xiaomi_reg_id": "...",
                    "platform": "android",
                    "registered_at": 1234567890.0,
                    "last_seen": 1234567890.0
                }
            }
        }
    }
    """

    def __init__(self, storage_path: Path | None = None) -> None:
        if storage_path is None:
            workspace = os.environ.get("NANOBOT_WORKSPACE", "~/.nanobot/workspace")
            storage_path = Path(workspace).expanduser() / "push_devices.json"
        self._path = storage_path
        self._lock = threading.Lock()
        self._ensure_file()

    def _ensure_file(self) -> None:
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text("{}")

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def register(
        self,
        user_token: str,
        device_id: str,
        *,
        fcm_token: str | None = None,
        xiaomi_reg_id: str | None = None,
        platform: str = "android",
    ) -> None:
        """Register or update a device's push token."""
        token_hash = hashlib.sha256(user_token.encode()).hexdigest()[:16]
        with self._lock:
            data = self._load()
            user_entry = data.setdefault(token_hash, {"devices": {}})
            devices = user_entry["devices"]
            device = devices.get(device_id, {})
            now = time.time()
            if not device:
                device = {"registered_at": now, "platform": platform}
            if fcm_token:
                device["fcm_token"] = fcm_token
            if xiaomi_reg_id:
                device["xiaomi_reg_id"] = xiaomi_reg_id
            device["last_seen"] = now
            devices[device_id] = device
            self._save(data)
            logger.info(
                "push device registered: user_hash={}, device_id={}, fcm={}, xiaomi={}",
                token_hash, device_id, bool(fcm_token), bool(xiaomi_reg_id),
            )

    def unregister(self, user_token: str, device_id: str) -> None:
        """Remove a device registration."""
        token_hash = hashlib.sha256(user_token.encode()).hexdigest()[:16]
        with self._lock:
            data = self._load()
            user_entry = data.get(token_hash)
            if user_entry and device_id in user_entry.get("devices", {}):
                del user_entry["devices"][device_id]
                if not user_entry["devices"]:
                    del data[token_hash]
                self._save(data)
                logger.info("push device unregistered: user_hash={}, device_id={}", token_hash, device_id)

    def get_devices(self, user_token: str) -> dict[str, Any]:
        """Get all registered devices for a user."""
        token_hash = hashlib.sha256(user_token.encode()).hexdigest()[:16]
        data = self._load()
        return data.get(token_hash, {}).get("devices", {})

    def get_all_user_tokens(self) -> list[str]:
        """Return all token hashes (for admin/debug)."""
        return list(self._load().keys())
