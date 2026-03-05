"""Feishu Streaming Card - Card Kit streaming API for real-time text output.

Uses the Feishu Card Kit API to create streaming cards that update in real-time,
giving users immediate visual feedback as the bot generates its response.

API Reference:
- Create card: POST /cardkit/v1/cards
- Update element: PUT /cardkit/v1/cards/{card_id}/elements/{element_id}/content
- Update settings: PATCH /cardkit/v1/cards/{card_id}/settings
"""

import json
import time
from typing import Any

import requests
from loguru import logger


# Token cache (keyed by app_id)
_token_cache: dict[str, dict[str, Any]] = {}

API_BASE = "https://open.feishu.cn/open-apis"


def _get_tenant_token(app_id: str, app_secret: str) -> str:
    """Get or refresh tenant access token with caching."""
    cached = _token_cache.get(app_id)
    if cached and cached["expires_at"] > time.time() + 60:
        return cached["token"]

    resp = requests.post(
        f"{API_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0 or not data.get("tenant_access_token"):
        raise RuntimeError(f"Failed to get tenant token: {data.get('msg', 'unknown error')}")

    token = data["tenant_access_token"]
    _token_cache[app_id] = {
        "token": token,
        "expires_at": time.time() + data.get("expire", 7200),
    }
    return token


def _truncate_summary(text: str, max_len: int = 50) -> str:
    """Create a short summary for the card."""
    if not text:
        return ""
    clean = text.replace("\n", " ").strip()
    return clean if len(clean) <= max_len else clean[: max_len - 3] + "..."


class FeishuStreamingCard:
    """Manages a single streaming card session.

    Lifecycle:
    1. start() - Create card entity + send card message
    2. update() - Update card content (throttled)
    3. close() - Final update + disable streaming mode
    """

    def __init__(self, app_id: str, app_secret: str, client: Any):
        self.app_id = app_id
        self.app_secret = app_secret
        self._client = client  # lark_oapi Client for sending messages
        self._card_id: str | None = None
        self._message_id: str | None = None
        self._sequence: int = 0
        self._current_text: str = ""
        self._closed: bool = False
        self._last_update_time: float = 0
        self._pending_text: str | None = None
        self._update_throttle_ms: int = 150  # Max ~6 updates/sec

    @property
    def is_active(self) -> bool:
        return self._card_id is not None and not self._closed

    def _auth_headers(self) -> dict[str, str]:
        token = _get_tenant_token(self.app_id, self.app_secret)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def start_sync(self, receive_id: str, receive_id_type: str = "chat_id") -> bool:
        """Create streaming card and send it. Returns True on success."""
        if self._card_id:
            return True

        card_json = {
            "schema": "2.0",
            "config": {
                "streaming_mode": True,
                "summary": {"content": "[Generating...]"},
                "streaming_config": {
                    "print_frequency_ms": {"default": 50},
                    "print_step": {"default": 2},
                },
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": "\u23f3 Thinking...",
                        "element_id": "content",
                    }
                ],
            },
        }

        try:
            # Step 1: Create card entity via Card Kit API
            create_resp = requests.post(
                f"{API_BASE}/cardkit/v1/cards",
                headers=self._auth_headers(),
                json={"type": "card_json", "data": json.dumps(card_json)},
                timeout=10,
            )
            create_data = create_resp.json()
            if create_data.get("code") != 0 or not create_data.get("data", {}).get("card_id"):
                logger.error("Failed to create streaming card: {}", create_data.get("msg"))
                return False

            self._card_id = create_data["data"]["card_id"]

            # Step 2: Send card message via IM API
            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

            content = json.dumps(
                {"type": "card", "data": {"card_id": self._card_id}},
                ensure_ascii=False,
            )
            request = (
                CreateMessageRequest.builder()
                .receive_id_type(receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(receive_id)
                    .msg_type("interactive")
                    .content(content)
                    .build()
                )
                .build()
            )
            response = self._client.im.v1.message.create(request)
            if not response.success() or not response.data:
                logger.error(
                    "Failed to send streaming card message: code={}, msg={}",
                    response.code,
                    response.msg,
                )
                self._card_id = None
                return False

            self._message_id = response.data.message_id
            logger.debug(
                "Streaming card started: card_id={}, message_id={}",
                self._card_id,
                self._message_id,
            )
            return True

        except Exception as e:
            logger.error("Error starting streaming card: {}", e)
            self._card_id = None
            return False

    def update_sync(self, text: str) -> None:
        """Update the card content. Throttled to avoid rate limits."""
        if not self._card_id or self._closed:
            return

        now = time.time() * 1000
        if now - self._last_update_time < self._update_throttle_ms:
            self._pending_text = text
            return

        self._pending_text = None
        self._last_update_time = now
        self._do_update(text)

    def _do_update(self, text: str) -> None:
        """Actually send the content update to the Card Kit API."""
        if not self._card_id:
            return

        self._sequence += 1
        self._current_text = text

        try:
            requests.put(
                f"{API_BASE}/cardkit/v1/cards/{self._card_id}/elements/content/content",
                headers=self._auth_headers(),
                json={
                    "content": text,
                    "sequence": self._sequence,
                    "uuid": f"s_{self._card_id}_{self._sequence}",
                },
                timeout=10,
            )
        except Exception as e:
            logger.debug("Streaming card update failed: {}", e)

    def flush_pending_sync(self) -> None:
        """Flush any pending throttled update."""
        if self._pending_text and not self._closed:
            self._do_update(self._pending_text)
            self._pending_text = None

    def close_sync(self, final_text: str | None = None) -> None:
        """Finalize the card: send last content update, then disable streaming mode."""
        if not self._card_id or self._closed:
            return

        self._closed = True
        text = final_text or self._pending_text or self._current_text

        # Send final content if it differs
        if text and text != self._current_text:
            self._do_update(text)

        # Disable streaming mode
        self._sequence += 1
        try:
            requests.patch(
                f"{API_BASE}/cardkit/v1/cards/{self._card_id}/settings",
                headers=self._auth_headers(),
                json={
                    "settings": json.dumps(
                        {
                            "config": {
                                "streaming_mode": False,
                                "summary": {"content": _truncate_summary(text or "")},
                            },
                        }
                    ),
                    "sequence": self._sequence,
                    "uuid": f"c_{self._card_id}_{self._sequence}",
                },
                timeout=10,
            )
        except Exception as e:
            logger.debug("Streaming card close failed: {}", e)

        logger.debug("Streaming card closed: card_id={}", self._card_id)
