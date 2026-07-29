"""Push notification senders: FCM and Xiaomi dual-channel.

Each sender reads credentials from environment variables.
If credentials are not configured, the sender is a no-op.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any

import httpx
from loguru import logger


class PushSender(ABC):
    """Base class for push notification senders."""

    @abstractmethod
    async def send(self, *, target: str, title: str, body: str, data: dict[str, Any] | None = None) -> bool:
        """Send a push notification to a device token/reg_id.

        Returns True if the message was accepted by the provider.
        """

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Whether this sender has valid credentials."""


class FCMSender(PushSender):
    """Send push via Firebase Cloud Messaging HTTP v1 API.

    Environment:
        FCM_SERVICE_ACCOUNT_JSON: Path to service account JSON file.
    """

    TOKEN_URL = "https://oauth2.googleapis.com/token"
    FCM_PROJECT_URL_TEMPLATE = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

    def __init__(self) -> None:
        self._service_account_path = os.environ.get("FCM_SERVICE_ACCOUNT_JSON", "")
        self._access_token: str | None = None
        self._token_expiry: float = 0

    @property
    def is_configured(self) -> bool:
        return bool(self._service_account_path and os.path.isfile(self._service_account_path))

    async def _get_access_token(self) -> str | None:
        """Obtain OAuth2 access token from service account."""
        import time

        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token

        try:
            sa = json.loads(open(self._service_account_path).read())
        except (OSError, json.JSONDecodeError) as e:
            logger.error("FCM: cannot read service account: {}", e)
            return None

        import jwt  # PyJWT

        now = int(time.time())
        payload = {
            "iss": sa["client_email"],
            "sub": sa["client_email"],
            "scope": "https://www.googleapis.com/auth/firebase.messaging",
            "aud": self.TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        }
        assertion = jwt.encode(payload, sa["private_key"], algorithm="RS256")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                timeout=10.0,
            )
            if resp.status_code != 200:
                logger.error("FCM: token request failed: {} {}", resp.status_code, resp.text)
                return None
            result = resp.json()
            self._access_token = result["access_token"]
            self._token_expiry = now + result.get("expires_in", 3600)
            return self._access_token

    async def send(self, *, target: str, title: str, body: str, data: dict[str, Any] | None = None) -> bool:
        if not self.is_configured:
            return False

        token = await self._get_access_token()
        if not token:
            return False

        try:
            sa = json.loads(open(self._service_account_path).read())
            project_id = sa["project_id"]
        except (OSError, json.DecodeError, KeyError):
            logger.error("FCM: cannot extract project_id from service account")
            return False

        url = self.FCM_PROJECT_URL_TEMPLATE.format(project_id=project_id)
        message: dict[str, Any] = {
            "message": {
                "token": target,
                "notification": {"title": title, "body": body},
                "android": {
                    "priority": "high",
                    "notification": {"channel_id": "jarvis_push", "click_action": "OPEN_ACTIVITY_1"},
                },
            }
        }
        if data:
            message["message"]["data"] = {k: str(v) for k, v in data.items()}

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json=message,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )
            if resp.status_code == 200:
                logger.info("FCM: sent to {}...", target[:12])
                return True
            logger.warning("FCM: send failed {} - {}", resp.status_code, resp.text[:200])
            return False


class XiaomiSender(PushSender):
    """Send push via Xiaomi Mi Push (MiPush) Pass-through API.

    Environment:
        XIAOMI_APP_ID: AppId from Xiaomi open platform.
        XIAOMI_APP_KEY: AppKey from Xiaomi open platform.
        XIAOMI_APP_SECRET: AppSecret for API authentication.
    """

    BASE_URL = "https://api.xmpush.xiaomi.com/v3/message/passthrough"

    def __init__(self) -> None:
        self._app_id = os.environ.get("XIAOMI_APP_ID", "")
        self._app_key = os.environ.get("XIAOMI_APP_KEY", "")
        self._app_secret = os.environ.get("XIAOMI_APP_SECRET", "")

    @property
    def is_configured(self) -> bool:
        return bool(self._app_secret and self._app_id and self._app_key)

    async def send(self, *, target: str, title: str, body: str, data: dict[str, Any] | None = None) -> bool:
        if not self.is_configured:
            return False

        # Xiaomi pass-through: raw JSON payload delivered to app's
        # PushMessageReceiverService.onReceivePassThroughMessage
        extra_data = data or {}
        payload = json.dumps({"title": title, "body": body, **extra_data}, ensure_ascii=False)

        params = {
            "registration_id": target,
            "title": title,
            "description": body,
            "payload": payload,
            "extra.notify_effect": "1",  # launcher activity
            "extra.notify_foreground": "1",
            "app_id": self._app_id,
            "app_key": self._app_key,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.BASE_URL,
                data=params,
                headers={"Authorization": f"key={self._app_secret}"},
                timeout=10.0,
            )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("result") == "ok":
                    logger.info("Xiaomi: sent to {}...", target[:12])
                    return True
                logger.warning("Xiaomi: send rejected - {}", result)
            else:
                logger.warning("Xiaomi: send failed {} - {}", resp.status_code, resp.text[:200])
            return False


class NoopSender(PushSender):
    """No-op sender when no credentials are configured."""

    @property
    def is_configured(self) -> bool:
        return False

    async def send(self, *, target: str, title: str, body: str, data: dict[str, Any] | None = None) -> bool:
        return False
