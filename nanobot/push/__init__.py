"""Mobile push notification bridge for nanobot.

Provides FCM + Xiaomi dual-channel push delivery when the agent completes
a turn and the user's app is in the background (no active WebSocket).

Environment variables:
    FCM_SERVICE_ACCOUNT_JSON: Path to FCM service account JSON file.
    XIAOMI_APP_ID: Xiaomi push AppId.
    XIAOMI_APP_KEY: Xiaomi push AppKey.
    XIAOMI_APP_SECRET: Xiaomi push AppSecret (for sending messages).
"""

from nanobot.push.service import PushService, get_push_service, init_push_service

__all__ = ["PushService", "get_push_service", "init_push_service"]
