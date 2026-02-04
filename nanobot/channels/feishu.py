import asyncio
import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import FeishuConfig


class FeishuChannel(BaseChannel):
    name = "feishu"

    def __init__(self, config: FeishuConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: FeishuConfig = config

        self._ws_client: Any | None = None
        self._ws_thread: threading.Thread | None = None

        self._ws_loop: asyncio.AbstractEventLoop | None = None
        self._ws_stop: Any | None = None

        self._loop: asyncio.AbstractEventLoop | None = None
        self._http: httpx.AsyncClient | None = None

        self._tenant_access_token: str | None = None
        self._tenant_token_expires_at: float = 0.0
        self._tenant_token_lock = asyncio.Lock()

    async def start(self) -> None:
        if not self.config.app_id or not self.config.app_secret:
            logger.error("Feishu app_id/app_secret not configured")
            return

        self._loop = asyncio.get_running_loop()
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

        self._running = True

        if not self._start_sdk_websocket():
            self._running = False
            return

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False

        if self._ws_loop and self._ws_stop is not None:
            try:
                self._ws_loop.call_soon_threadsafe(self._ws_stop.set)
            except Exception as e:
                logger.debug(f"Feishu ws stop signal failed: {e}")

        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=2.0)
        self._ws_thread = None

        self._ws_client = None
        self._ws_loop = None
        self._ws_stop = None

        if self._http:
            await self._http.aclose()
            self._http = None

    async def send(self, msg: OutboundMessage) -> None:
        if not self._http:
            logger.warning("Feishu HTTP client not initialized")
            return

        uuid = msg.metadata.get("uuid") if isinstance(msg.metadata, dict) else None
        if uuid is not None and not isinstance(uuid, str):
            uuid = str(uuid)

        base_reply_to = msg.reply_to
        msg_type = None
        if isinstance(msg.metadata, dict):
            raw = msg.metadata.get("msg_type") or msg.metadata.get("feishu_msg_type")
            if isinstance(raw, str):
                msg_type = raw
        msg_type = msg_type or "text"

        content = msg.content.lstrip("\n") if msg.content else ""
        if content:
            await self._send_content(
                chat_id=msg.chat_id,
                content=content,
                msg_type=msg_type,
                reply_to=base_reply_to,
                uuid=uuid,
            )

        if msg.media:
            for entry in msg.media:
                try:
                    local_path = await self._resolve_media_entry(entry)
                    if self._is_image_path(local_path):
                        image_key = await self._upload_image(local_path)
                        await self._send_image(
                            chat_id=msg.chat_id,
                            image_key=image_key,
                            reply_to=base_reply_to,
                            uuid=uuid,
                        )
                    else:
                        file_key = await self._upload_file(local_path)
                        await self._send_file(
                            chat_id=msg.chat_id,
                            file_key=file_key,
                            reply_to=base_reply_to,
                            uuid=uuid,
                        )
                except Exception as e:
                    logger.error(f"Feishu media send failed: {e}")
                    if isinstance(entry, str) and entry.startswith(("http://", "https://")):
                        await self._send_content(
                            chat_id=msg.chat_id,
                            content=entry,
                            msg_type="text",
                            reply_to=base_reply_to,
                            uuid=uuid,
                        )

    def _start_sdk_websocket(self) -> bool:
        try:
            import lark_oapi as lark
        except Exception as e:
            logger.error(f"Feishu websocket mode requires 'lark-oapi' package: {e}")
            return False

        def on_message(data: Any) -> None:
            if not self._loop:
                return
            try:
                payload = json.loads(lark.JSON.marshal(data))
            except Exception:
                return
            asyncio.run_coroutine_threadsafe(self._process_message_event(payload), self._loop)

        token = self.config.verification_token or ""
        encrypt_key = self.config.encrypt_key or ""
        event_handler = (
            lark.EventDispatcherHandler.builder(encrypt_key, token, lark.LogLevel.INFO)
            .register_p2_im_message_receive_v1(on_message)
            .build()
        )

        self._ws_client = lark.ws.Client(
            self.config.app_id,
            self.config.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        def run() -> None:
            ws_loop: asyncio.AbstractEventLoop | None = None
            stop_event: Any | None = None
            try:
                import lark_oapi.ws.client as ws_client_mod

                ws_loop = asyncio.new_event_loop()
                ws_client_mod.loop = ws_loop
                asyncio.set_event_loop(ws_loop)

                stop_event = asyncio.Event()
                self._ws_loop = ws_loop
                self._ws_stop = stop_event

                async def runner() -> None:
                    try:
                        try:
                            await self._ws_client._connect()
                        except Exception as e:
                            if getattr(self._ws_client, "_auto_reconnect", False):
                                logger.error(f"Feishu websocket connect failed, reconnecting: {e}")
                                await self._ws_client._reconnect()
                            else:
                                raise

                        ws_loop.create_task(self._ws_client._ping_loop())
                        logger.info("Feishu websocket connected (SDK)")
                        await stop_event.wait()
                    finally:
                        try:
                            await self._ws_client._disconnect()
                        except Exception as e:
                            logger.debug(f"Feishu websocket disconnect failed: {e}")

                ws_loop.run_until_complete(runner())
            except Exception as e:
                logger.error(f"Feishu websocket client exited: {e}")
            finally:
                if ws_loop is not None:
                    try:
                        pending = asyncio.all_tasks(ws_loop)
                        for t in pending:
                            t.cancel()
                        ws_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    except Exception:
                        pass
                    try:
                        ws_loop.close()
                    except Exception:
                        pass

        self._ws_thread = threading.Thread(target=run, daemon=True)
        self._ws_thread.start()
        return True

    async def _process_message_event(self, payload: dict[str, Any]) -> None:
        event = payload.get("event") or {}
        message = event.get("message") or {}
        sender = event.get("sender") or {}

        message_id = message.get("message_id")
        chat_id = message.get("chat_id")
        chat_type = message.get("chat_type")
        message_type = message.get("message_type") or message.get("msg_type")
        content_raw = message.get("content") or ""

        sender_id_obj = sender.get("sender_id") or {}
        sender_open_id = sender_id_obj.get("open_id")
        sender_user_id = sender_id_obj.get("user_id")
        sender_union_id = sender_id_obj.get("union_id")

        sender_id = (
            sender_open_id
            or sender_user_id
            or sender_union_id
            or sender.get("open_id")
            or sender.get("user_id")
            or ""
        )

        mentions = message.get("mentions") or []
        mentioned_bot = self._check_bot_mentioned(mentions)

        is_group = chat_type == "group"
        if is_group and self.config.group_policy == "mention-only" and not mentioned_bot:
            return

        text = self._parse_text_content(content_raw, message_type)

        metadata: dict[str, Any] = {
            "message_id": message_id,
            "chat_type": chat_type,
            "message_type": message_type,
            "mentioned_bot": mentioned_bot,
            "sender_open_id": sender_open_id,
        }

        media_paths: list[str] = []

        if message_type in {"image", "file"} and isinstance(content_raw, str) and message_id:
            try:
                parsed = json.loads(content_raw) if content_raw else {}
                if message_type == "image":
                    image_key = parsed.get("image_key")
                    if image_key:
                        metadata["image_key"] = image_key
                        saved = await self._download_message_resource(
                            message_id=message_id,
                            file_key=image_key,
                            resource_type="image",
                        )
                        if saved:
                            media_paths.append(saved)
                elif message_type == "file":
                    file_key = parsed.get("file_key")
                    if file_key:
                        metadata["file_key"] = file_key
                        saved = await self._download_message_resource(
                            message_id=message_id,
                            file_key=file_key,
                            resource_type="file",
                        )
                        if saved:
                            media_paths.append(saved)
            except Exception as e:
                logger.error(f"Feishu inbound media handling failed: {e}")

        await self._handle_message(
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=text,
            media=media_paths,
            metadata=metadata,
        )

    def _check_bot_mentioned(self, mentions: Any) -> bool:
        if not isinstance(mentions, list) or not mentions:
            return False

        bot_open_id = self.config.bot_open_id.strip() if self.config.bot_open_id else ""
        if not bot_open_id:
            return True

        for m in mentions:
            if not isinstance(m, dict):
                continue
            m_id = m.get("id") or {}
            if isinstance(m_id, dict) and m_id.get("open_id") == bot_open_id:
                return True
        return False

    def _parse_text_content(self, raw: str, message_type: str | None) -> str:
        if not raw:
            return ""
        if message_type != "text":
            return raw
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and isinstance(parsed.get("text"), str):
                return parsed["text"]
        except Exception:
            return raw
        return raw

    async def _get_tenant_access_token(self) -> str:
        if not self._http:
            raise RuntimeError("HTTP client not initialized")

        now = time.time()
        if self._tenant_access_token and now < self._tenant_token_expires_at:
            return self._tenant_access_token

        async with self._tenant_token_lock:
            now = time.time()
            if self._tenant_access_token and now < self._tenant_token_expires_at:
                return self._tenant_access_token

            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            resp = await self._http.post(
                url,
                json={"app_id": self.config.app_id, "app_secret": self.config.app_secret},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"Feishu token error: {data.get('msg')}")
            token = data.get("tenant_access_token")
            expires_in = int(data.get("expire") or 0)
            if not token or expires_in <= 0:
                raise RuntimeError("Feishu token missing or invalid")

            self._tenant_access_token = token
            self._tenant_token_expires_at = time.time() + max(0, expires_in - 60)
            return token

    async def _send_content(
        self,
        chat_id: str,
        content: str,
        msg_type: str,
        reply_to: str | None,
        uuid: str | None,
    ) -> None:
        if msg_type not in {"text", "post", "interactive"}:
            msg_type = "text"

        if msg_type == "text":
            body_content = json.dumps({"text": content}, ensure_ascii=False)
        elif msg_type == "post":
            body_content = self._build_post_content(content)
        else:
            body_content = self._build_interactive_content(content)

        await self._send_message(
            chat_id=chat_id,
            msg_type=msg_type,
            content=body_content,
            reply_to=reply_to,
            uuid=uuid,
        )

    async def _send_image(
        self,
        chat_id: str,
        image_key: str,
        reply_to: str | None,
        uuid: str | None,
    ) -> None:
        await self._send_message(
            chat_id=chat_id,
            msg_type="image",
            content=json.dumps({"image_key": image_key}, ensure_ascii=False),
            reply_to=reply_to,
            uuid=uuid,
        )

    async def _send_file(
        self,
        chat_id: str,
        file_key: str,
        reply_to: str | None,
        uuid: str | None,
    ) -> None:
        await self._send_message(
            chat_id=chat_id,
            msg_type="file",
            content=json.dumps({"file_key": file_key}, ensure_ascii=False),
            reply_to=reply_to,
            uuid=uuid,
        )

    def _build_post_content(self, text: str) -> str:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return json.dumps(parsed, ensure_ascii=False)
        except Exception:
            pass

        payload = {
            "zh_cn": {
                "content": [
                    [
                        {
                            "tag": "md",
                            "text": text,
                        }
                    ]
                ]
            }
        }
        return json.dumps(payload, ensure_ascii=False)

    def _build_interactive_content(self, raw: str) -> str:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return json.dumps(parsed, ensure_ascii=False)
        except Exception:
            pass
        return json.dumps(
            {"config": {"wide_screen_mode": True}, "elements": []}, ensure_ascii=False
        )

    async def _send_message(
        self,
        chat_id: str,
        msg_type: str,
        content: str,
        reply_to: str | None,
        uuid: str | None,
    ) -> None:
        if not self._http:
            raise RuntimeError("HTTP client not initialized")

        token = await self._get_tenant_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        if reply_to:
            url = f"https://open.feishu.cn/open-apis/im/v1/messages/{reply_to}/reply"
            payload: dict[str, Any] = {
                "msg_type": msg_type,
                "content": content,
            }
            if uuid:
                payload["uuid"] = uuid

            resp = await self._http.post(url, headers=headers, json=payload)
        else:
            url = "https://open.feishu.cn/open-apis/im/v1/messages"
            payload = {
                "receive_id": chat_id,
                "msg_type": msg_type,
                "content": content,
            }
            if uuid:
                payload["uuid"] = uuid

            resp = await self._http.post(
                url,
                headers=headers,
                params={"receive_id_type": "chat_id"},
                json=payload,
            )

        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Feishu send failed: {data.get('msg')}")

    async def _resolve_media_entry(self, entry: str) -> Path:
        if entry.startswith(("http://", "https://")):
            return await self._download_url_to_file(entry)

        p = Path(entry).expanduser()
        if not p.exists() or not p.is_file():
            raise FileNotFoundError(str(p))
        return p

    async def _download_url_to_file(self, url: str) -> Path:
        if not self._http:
            raise RuntimeError("HTTP client not initialized")

        media_dir = Path.home() / ".nanobot" / "media" / "feishu"
        media_dir.mkdir(parents=True, exist_ok=True)

        parsed = urlparse(url)
        name = Path(parsed.path).name
        if not name:
            name = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

        target = media_dir / name

        async with self._http.stream("GET", url, follow_redirects=True) as r:
            r.raise_for_status()
            with open(target, "wb") as f:
                async for chunk in r.aiter_bytes():
                    f.write(chunk)

        return target

    def _is_image_path(self, path: Path) -> bool:
        ext = path.suffix.lower()
        return ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".ico", ".tiff", ".heic"}

    async def _upload_image(self, path: Path) -> str:
        if not self._http:
            raise RuntimeError("HTTP client not initialized")

        token = await self._get_tenant_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        url = "https://open.feishu.cn/open-apis/im/v1/images"

        with open(path, "rb") as f:
            resp = await self._http.post(
                url,
                headers=headers,
                data={"image_type": "message"},
                files={"image": (path.name, f)},
            )

        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Feishu image upload failed: {data.get('msg')}")
        image_key = (data.get("data") or {}).get("image_key")
        if not image_key:
            raise RuntimeError("Feishu image upload failed: missing image_key")
        return str(image_key)

    async def _upload_file(self, path: Path) -> str:
        if not self._http:
            raise RuntimeError("HTTP client not initialized")

        token = await self._get_tenant_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        url = "https://open.feishu.cn/open-apis/im/v1/files"
        file_type = self._detect_file_type(path)

        with open(path, "rb") as f:
            resp = await self._http.post(
                url,
                headers=headers,
                data={
                    "file_type": file_type,
                    "file_name": path.name,
                },
                files={"file": (path.name, f)},
            )

        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Feishu file upload failed: {data.get('msg')}")
        file_key = (data.get("data") or {}).get("file_key")
        if not file_key:
            raise RuntimeError("Feishu file upload failed: missing file_key")
        return str(file_key)

    def _detect_file_type(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext == ".pdf":
            return "pdf"
        if ext in {".doc", ".docx"}:
            return "doc"
        if ext in {".xls", ".xlsx"}:
            return "xls"
        if ext in {".ppt", ".pptx"}:
            return "ppt"
        if ext == ".mp4":
            return "mp4"
        if ext == ".opus":
            return "opus"
        return "stream"

    async def _download_message_resource(
        self,
        message_id: str,
        file_key: str,
        resource_type: str,
    ) -> str | None:
        if not self._http:
            raise RuntimeError("HTTP client not initialized")

        token = await self._get_tenant_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{file_key}"

        media_dir = Path.home() / ".nanobot" / "media" / "feishu" / "inbound"
        media_dir.mkdir(parents=True, exist_ok=True)

        async with self._http.stream(
            "GET",
            url,
            headers=headers,
            params={"type": resource_type},
        ) as r:
            r.raise_for_status()
            filename = self._guess_filename(r.headers, message_id, file_key)
            target = media_dir / filename
            with open(target, "wb") as f:
                async for chunk in r.aiter_bytes():
                    f.write(chunk)

        return str(target)

    def _guess_filename(self, headers: httpx.Headers, message_id: str, file_key: str) -> str:
        cd = headers.get("Content-Disposition")
        if cd and "filename=" in cd:
            raw = cd.split("filename=", 1)[1].strip().strip('"')
            if raw:
                return raw

        content_type = headers.get("Content-Type", "")
        ext = self._ext_from_content_type(content_type)
        return f"{message_id[:16]}_{file_key[:16]}{ext}"

    def _ext_from_content_type(self, content_type: str) -> str:
        ct = content_type.split(";", 1)[0].strip().lower()
        mapping = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "application/pdf": ".pdf",
        }
        return mapping.get(ct, "")
