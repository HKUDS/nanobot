"""WeChat channel implementation using openclaw-weixin ilink HTTP API.

Supports login via QR code scanning, long-poll message receiving (getUpdates),
text message sending (sendMessage), and typing indicators.

Protocol reference: https://www.npmjs.com/package/@tencent-weixin/openclaw-weixin
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import struct
import time
from pathlib import Path

import httpx
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WeixinConfig
from nanobot.utils.helpers import split_message

WEIXIN_MAX_MESSAGE_LEN = 4000
DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_LONG_POLL_TIMEOUT_MS = 35_000
DEFAULT_API_TIMEOUT_MS = 15_000
QR_LONG_POLL_TIMEOUT_MS = 35_000
DEFAULT_BOT_TYPE = "3"
MAX_CONSECUTIVE_FAILURES = 3
BACKOFF_DELAY_MS = 30_000
RETRY_DELAY_MS = 2_000
SESSION_EXPIRED_ERRCODE = -14


def _random_wechat_uin() -> str:
    """X-WECHAT-UIN header: random uint32 -> decimal string -> base64."""
    raw = os.urandom(4)
    uint32 = struct.unpack(">I", raw)[0]
    return base64.b64encode(str(uint32).encode()).decode()


def _build_headers(token: str | None) -> dict[str, str]:
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": _random_wechat_uin(),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _generate_client_id() -> str:
    return f"nanobot-wx-{int(time.time() * 1000)}-{os.urandom(4).hex()}"


# ── Account persistence ──────────────────────────────────────────────────────


def _state_dir() -> Path:
    d = Path.home() / ".nanobot" / "weixin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_id(account_id: str) -> str:
    return account_id.replace("@", "-").replace(".", "-")


def load_account(account_id: str) -> dict | None:
    p = _state_dir() / f"{_safe_id(account_id)}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def save_account(account_id: str, data: dict) -> None:
    p = _state_dir() / f"{_safe_id(account_id)}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))
    try:
        p.chmod(0o600)
    except Exception:
        pass


def _load_sync_buf(account_id: str) -> str:
    p = _state_dir() / f"sync_{_safe_id(account_id)}.txt"
    if p.exists():
        return p.read_text().strip()
    return ""


def _save_sync_buf(account_id: str, buf: str) -> None:
    (_state_dir() / f"sync_{_safe_id(account_id)}.txt").write_text(buf)


# ── QR Login ──────────────────────────────────────────────────────────────────


async def fetch_qr_code(base_url: str) -> dict:
    url = f"{base_url.rstrip('/')}/ilink/bot/get_bot_qrcode?bot_type={DEFAULT_BOT_TYPE}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def poll_qr_status(base_url: str, qrcode: str) -> dict:
    url = f"{base_url.rstrip('/')}/ilink/bot/get_qrcode_status?qrcode={qrcode}"
    headers = {"iLink-App-ClientVersion": "1"}
    async with httpx.AsyncClient(timeout=QR_LONG_POLL_TIMEOUT_MS / 1000 + 5) as client:
        try:
            resp = await client.get(url, headers=headers, timeout=QR_LONG_POLL_TIMEOUT_MS / 1000)
            resp.raise_for_status()
            return resp.json()
        except httpx.ReadTimeout:
            return {"status": "wait"}


async def weixin_qr_login(base_url: str = DEFAULT_BASE_URL, timeout_s: int = 480) -> dict | None:
    """Perform QR code login. Returns account data dict or None on failure."""
    import sys

    print("Fetching WeChat QR code...")
    qr_resp = await fetch_qr_code(base_url)
    qrcode = qr_resp.get("qrcode", "")
    qrcode_url = qr_resp.get("qrcode_img_content", "")

    if not qrcode or not qrcode_url:
        print("Failed to get QR code from server.")
        return None

    try:
        import qrcode as qr_lib
        qr = qr_lib.QRCode(error_correction=qr_lib.constants.ERROR_CORRECT_L, box_size=1, border=1)
        qr.add_data(qrcode_url)
        qr.make(fit=True)
        qr.print_ascii(out=sys.stdout, invert=True)
    except ImportError:
        print(f"QR Code URL: {qrcode_url}")
        print("(Install 'qrcode' package for terminal QR display: pip install qrcode)")

    print("\nScan with WeChat to connect...\n")

    deadline = asyncio.get_event_loop().time() + timeout_s
    scanned_printed = False

    while asyncio.get_event_loop().time() < deadline:
        status_resp = await poll_qr_status(base_url, qrcode)
        status = status_resp.get("status", "wait")

        if status == "scaned" and not scanned_printed:
            print("Scanned! Confirm on your phone...")
            scanned_printed = True
        elif status == "expired":
            print("QR code expired, refreshing...")
            qr_resp = await fetch_qr_code(base_url)
            qrcode = qr_resp.get("qrcode", "")
            qrcode_url = qr_resp.get("qrcode_img_content", "")
            if not qrcode:
                print("Failed to refresh QR code.")
                return None
            try:
                qr = qr_lib.QRCode(error_correction=qr_lib.constants.ERROR_CORRECT_L, box_size=1, border=1)
                qr.add_data(qrcode_url)
                qr.make(fit=True)
                qr.print_ascii(out=sys.stdout, invert=True)
            except Exception:
                print(f"New QR Code URL: {qrcode_url}")
            scanned_printed = False
        elif status == "confirmed":
            bot_token = status_resp.get("bot_token")
            bot_id = status_resp.get("ilink_bot_id")
            resp_base_url = status_resp.get("baseurl", base_url)
            user_id = status_resp.get("ilink_user_id", "")

            if not bot_id:
                print("Login confirmed but server did not return bot ID.")
                return None

            account_data = {
                "token": bot_token,
                "base_url": resp_base_url or base_url,
                "account_id": bot_id,
                "user_id": user_id,
            }
            save_account(bot_id, account_data)
            print(f"\nWeChat connected! Account: {bot_id}")
            return account_data

        await asyncio.sleep(1)

    print("Login timed out.")
    return None


# ── API helpers ───────────────────────────────────────────────────────────────


async def _api_get_updates(
    client: httpx.AsyncClient,
    base_url: str,
    token: str | None,
    get_updates_buf: str,
    timeout_ms: int = DEFAULT_LONG_POLL_TIMEOUT_MS,
) -> dict:
    url = f"{base_url.rstrip('/')}/ilink/bot/getupdates"
    body = {"get_updates_buf": get_updates_buf}
    headers = _build_headers(token)
    resp = await client.post(url, json=body, headers=headers, timeout=timeout_ms / 1000 + 5)
    resp.raise_for_status()
    return resp.json()


async def _api_send_message(
    client: httpx.AsyncClient,
    base_url: str,
    token: str | None,
    to_user_id: str,
    text: str,
    context_token: str | None = None,
) -> None:
    url = f"{base_url.rstrip('/')}/ilink/bot/sendmessage"
    item_list = [{"type": 1, "text_item": {"text": text}}] if text else []
    body = {
        "msg": {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": _generate_client_id(),
            "message_type": 2,   # BOT
            "message_state": 2,  # FINISH
            "item_list": item_list or None,
            "context_token": context_token,
        }
    }
    headers = _build_headers(token)
    resp = await client.post(url, json=body, headers=headers, timeout=DEFAULT_API_TIMEOUT_MS / 1000)
    resp.raise_for_status()


async def _api_send_typing(
    client: httpx.AsyncClient,
    base_url: str,
    token: str | None,
    user_id: str,
    typing_ticket: str,
    status: int = 1,
) -> None:
    url = f"{base_url.rstrip('/')}/ilink/bot/sendtyping"
    body = {"ilink_user_id": user_id, "typing_ticket": typing_ticket, "status": status}
    headers = _build_headers(token)
    try:
        resp = await client.post(url, json=body, headers=headers, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.debug("sendTyping failed: {}", e)


async def _api_get_config(
    client: httpx.AsyncClient,
    base_url: str,
    token: str | None,
    user_id: str,
    context_token: str | None = None,
) -> dict:
    url = f"{base_url.rstrip('/')}/ilink/bot/getconfig"
    body: dict = {"ilink_user_id": user_id}
    if context_token:
        body["context_token"] = context_token
    headers = _build_headers(token)
    resp = await client.post(url, json=body, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


# ── Channel ───────────────────────────────────────────────────────────────────


class WeixinChannel(BaseChannel):
    """WeChat channel using openclaw-weixin ilink HTTP long-poll API."""

    name = "weixin"

    def __init__(self, config: WeixinConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: WeixinConfig = config
        self._client: httpx.AsyncClient | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._typing_tickets: dict[str, str] = {}
        self._context_tokens: dict[str, str] = {}

    async def start(self) -> None:
        token = self.config.token
        account_id = self.config.account_id
        base_url = self.config.base_url or DEFAULT_BASE_URL

        if not token or not account_id:
            acct = load_account(account_id) if account_id else None
            if acct:
                token = token or acct.get("token", "")
                account_id = account_id or acct.get("account_id", "")
                base_url = acct.get("base_url", base_url)

        if not token:
            logger.error("WeChat token not configured. Run: nanobot channels weixin-login")
            return

        self._running = True
        self._client = httpx.AsyncClient()
        logger.info("Starting WeChat channel (account={}, base_url={})", account_id, base_url)

        get_updates_buf = _load_sync_buf(account_id) if account_id else ""
        next_timeout_ms = self.config.poll_timeout_ms or DEFAULT_LONG_POLL_TIMEOUT_MS
        consecutive_failures = 0

        while self._running:
            try:
                resp = await _api_get_updates(
                    self._client, base_url, token, get_updates_buf, next_timeout_ms
                )

                if resp.get("longpolling_timeout_ms"):
                    next_timeout_ms = resp["longpolling_timeout_ms"]

                ret = resp.get("ret", 0)
                errcode = resp.get("errcode", 0)

                if ret != 0 or errcode != 0:
                    if errcode == SESSION_EXPIRED_ERRCODE or ret == SESSION_EXPIRED_ERRCODE:
                        logger.error("WeChat session expired (errcode {}), pausing 5 min", errcode)
                        await asyncio.sleep(300)
                        continue
                    consecutive_failures += 1
                    logger.warning(
                        "WeChat getUpdates error: ret={} errcode={} errmsg={} ({}/{})",
                        ret, errcode, resp.get("errmsg", ""),
                        consecutive_failures, MAX_CONSECUTIVE_FAILURES,
                    )
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        consecutive_failures = 0
                        await asyncio.sleep(BACKOFF_DELAY_MS / 1000)
                    else:
                        await asyncio.sleep(RETRY_DELAY_MS / 1000)
                    continue

                consecutive_failures = 0
                new_buf = resp.get("get_updates_buf", "")
                if new_buf:
                    get_updates_buf = new_buf
                    if account_id:
                        _save_sync_buf(account_id, new_buf)

                for msg in resp.get("msgs", []):
                    await self._process_inbound(msg, base_url, token)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._running:
                    break
                consecutive_failures += 1
                logger.error("WeChat poll error ({}/{}): {}",
                             consecutive_failures, MAX_CONSECUTIVE_FAILURES, e)
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    consecutive_failures = 0
                    await asyncio.sleep(BACKOFF_DELAY_MS / 1000)
                else:
                    await asyncio.sleep(RETRY_DELAY_MS / 1000)

    async def _process_inbound(self, msg: dict, base_url: str, token: str | None) -> None:
        from_user_id = msg.get("from_user_id", "")
        message_type = msg.get("message_type", 0)
        context_token = msg.get("context_token")

        if message_type != 1:  # only user messages
            return
        if not from_user_id:
            return

        if context_token:
            self._context_tokens[from_user_id] = context_token

        item_list = msg.get("item_list", []) or []
        text_parts: list[str] = []
        for item in item_list:
            item_type = item.get("type", 0)
            if item_type == 1:  # TEXT
                text = item.get("text_item", {}).get("text", "")
                ref_msg = item.get("ref_msg")
                if ref_msg and ref_msg.get("title"):
                    text_parts.append(f"[quote: {ref_msg['title']}]")
                if text:
                    text_parts.append(text)
            elif item_type == 3:  # VOICE
                voice_text = item.get("voice_item", {}).get("text", "")
                if voice_text:
                    text_parts.append(f"[voice: {voice_text}]")
            elif item_type == 2:  # IMAGE
                text_parts.append("[image]")
            elif item_type == 4:  # FILE
                fname = item.get("file_item", {}).get("file_name", "file")
                text_parts.append(f"[file: {fname}]")
            elif item_type == 5:  # VIDEO
                text_parts.append("[video]")

        content = "\n".join(text_parts) if text_parts else "[empty message]"
        logger.info("WeChat message from {}: {}...", from_user_id, content[:80])

        if self._client and from_user_id not in self._typing_tickets:
            try:
                cfg_resp = await _api_get_config(
                    self._client, base_url, token, from_user_id, context_token
                )
                ticket = cfg_resp.get("typing_ticket", "")
                if ticket:
                    self._typing_tickets[from_user_id] = ticket
            except Exception as e:
                logger.debug("Failed to get typing config for {}: {}", from_user_id, e)

        self._start_typing(from_user_id, base_url, token)

        await self._handle_message(
            sender_id=from_user_id,
            chat_id=from_user_id,
            content=content,
            metadata={
                "context_token": context_token,
                "message_id": msg.get("message_id"),
                "session_id": msg.get("session_id"),
            },
        )

    def _start_typing(self, user_id: str, base_url: str, token: str | None) -> None:
        self._stop_typing(user_id)
        self._typing_tasks[user_id] = asyncio.create_task(
            self._typing_loop(user_id, base_url, token)
        )

    def _stop_typing(self, user_id: str) -> None:
        task = self._typing_tasks.pop(user_id, None)
        if task and not task.done():
            task.cancel()

    async def _typing_loop(self, user_id: str, base_url: str, token: str | None) -> None:
        ticket = self._typing_tickets.get(user_id, "")
        if not ticket or not self._client:
            return
        try:
            while True:
                await _api_send_typing(self._client, base_url, token, user_id, ticket, status=1)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Typing loop stopped for {}: {}", user_id, e)

    async def send(self, msg: OutboundMessage) -> None:
        if not self._client:
            logger.warning("WeChat client not initialized")
            return

        # Skip progress/streaming messages -- WeChat has no partial update support
        if msg.metadata.get("_progress", False):
            return

        self._stop_typing(msg.chat_id)

        base_url = self.config.base_url or DEFAULT_BASE_URL
        token = self.config.token

        if not token:
            account_id = self.config.account_id
            if account_id:
                acct = load_account(account_id)
                if acct:
                    token = acct.get("token", "")
                    base_url = acct.get("base_url", base_url)

        context_token = (
            msg.metadata.get("context_token")
            or self._context_tokens.get(msg.chat_id)
        )

        if msg.content and msg.content != "[empty message]":
            for chunk in split_message(msg.content, WEIXIN_MAX_MESSAGE_LEN):
                try:
                    await _api_send_message(
                        self._client, base_url, token,
                        to_user_id=msg.chat_id,
                        text=chunk,
                        context_token=context_token,
                    )
                except Exception as e:
                    logger.error("Failed to send WeChat message to {}: {}", msg.chat_id, e)

    async def stop(self) -> None:
        self._running = False
        for user_id in list(self._typing_tasks):
            self._stop_typing(user_id)
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("WeChat channel stopped")
