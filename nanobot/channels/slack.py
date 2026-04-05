"""Slack channel implementation using Socket Mode."""

import asyncio
import re
from typing import Any

import httpx
from loguru import logger
from pydantic import Field
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.websockets import SocketModeClient
from slack_sdk.web.async_client import AsyncWebClient
from slackify_markdown import slackify_markdown

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base


class SlackDMConfig(Base):
    """Slack DM policy configuration."""

    enabled: bool = True
    policy: str = "open"
    allow_from: list[str] = Field(default_factory=list)


class SlackConfig(Base):
    """Slack channel configuration."""

    enabled: bool = False
    mode: str = "socket"
    webhook_path: str = "/slack/events"
    bot_token: str = ""
    app_token: str = ""
    user_token_read_only: bool = True
    reply_in_thread: bool = True
    react_emoji: str = "eyes"
    done_emoji: str = "white_check_mark"
    allow_from: list[str] = Field(default_factory=list)
    group_policy: str = "mention"
    group_allow_from: list[str] = Field(default_factory=list)
    dm: SlackDMConfig = Field(default_factory=SlackDMConfig)
    max_file_size: int = Field(default=26214400)  # 25MB default


class SlackChannel(BaseChannel):
    """Slack channel using Socket Mode."""

    name = "slack"
    display_name = "Slack"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return SlackConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = SlackConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: SlackConfig = config
        self._web_client: AsyncWebClient | None = None
        self._socket_client: SocketModeClient | None = None
        self._bot_user_id: str | None = None

    async def start(self) -> None:
        """Start the Slack Socket Mode client."""
        if not self.config.bot_token or not self.config.app_token:
            logger.error("Slack bot/app token not configured")
            return
        if self.config.mode != "socket":
            logger.error("Unsupported Slack mode: {}", self.config.mode)
            return

        self._running = True

        self._web_client = AsyncWebClient(token=self.config.bot_token)
        self._socket_client = SocketModeClient(
            app_token=self.config.app_token,
            web_client=self._web_client,
        )

        self._socket_client.socket_mode_request_listeners.append(self._on_socket_request)

        # Resolve bot user ID for mention handling
        try:
            auth = await self._web_client.auth_test()
            self._bot_user_id = auth.get("user_id")
            logger.info("Slack bot connected as {}", self._bot_user_id)
        except Exception as e:
            logger.warning("Slack auth_test failed: {}", e)

        logger.info("Starting Slack Socket Mode client...")
        await self._socket_client.connect()

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the Slack client."""
        self._running = False
        if self._socket_client:
            try:
                await self._socket_client.close()
            except Exception as e:
                logger.warning("Slack socket close failed: {}", e)
            self._socket_client = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Slack."""
        if not self._web_client:
            logger.warning("Slack client not running")
            return
        try:
            slack_meta = msg.metadata.get("slack", {}) if msg.metadata else {}
            thread_ts = slack_meta.get("thread_ts")
            channel_type = slack_meta.get("channel_type")
            # Slack DMs don't use threads; channel/group replies may keep thread_ts.
            thread_ts_param = thread_ts if thread_ts and channel_type != "im" else None

            # Slack rejects empty text payloads. Keep media-only messages media-only,
            # but send a single blank message when the bot has no text or files to send.
            if msg.content or not (msg.media or []):
                await self._web_client.chat_postMessage(
                    channel=msg.chat_id,
                    text=self._to_mrkdwn(msg.content) if msg.content else " ",
                    thread_ts=thread_ts_param,
                )

            for media_path in msg.media or []:
                try:
                    await self._web_client.files_upload_v2(
                        channel=msg.chat_id,
                        file=media_path,
                        thread_ts=thread_ts_param,
                    )
                except Exception as e:
                    logger.error("Failed to upload file {}: {}", media_path, e)

            # Update reaction emoji when the final (non-progress) response is sent
            if not (msg.metadata or {}).get("_progress"):
                event = slack_meta.get("event", {})
                await self._update_react_emoji(msg.chat_id, event.get("ts"))

        except Exception as e:
            logger.error("Error sending Slack message: {}", e)
            raise

    async def _on_socket_request(
        self,
        client: SocketModeClient,
        req: SocketModeRequest,
    ) -> None:
        """Handle incoming Socket Mode requests."""
        if req.type != "events_api":
            return

        # Acknowledge right away
        await client.send_socket_mode_response(
            SocketModeResponse(envelope_id=req.envelope_id)
        )

        payload = req.payload or {}
        event = payload.get("event") or {}
        event_type = event.get("type")

        # Handle app mentions or plain messages
        if event_type not in ("message", "app_mention"):
            return

        sender_id = event.get("user")
        chat_id = event.get("channel")

        # Ignore bot/system messages, but allow file_share for media support
        subtype = event.get("subtype")
        if subtype and subtype not in ("file_share",):
            return
        if self._bot_user_id and sender_id == self._bot_user_id:
            return

        # Avoid double-processing: Slack sends both `message` and `app_mention`
        # for mentions in channels. Prefer `app_mention`.
        text = event.get("text") or ""
        if event_type == "message" and self._bot_user_id and f"<@{self._bot_user_id}>" in text:
            return

        # Debug: log basic event shape
        logger.debug(
            "Slack event: type={} subtype={} user={} channel={} channel_type={} text={}",
            event_type,
            event.get("subtype"),
            sender_id,
            chat_id,
            event.get("channel_type"),
            text[:80],
        )
        if not sender_id or not chat_id:
            return

        channel_type = event.get("channel_type") or ""

        if not self._is_allowed(sender_id, chat_id, channel_type):
            return

        if channel_type != "im" and not self._should_respond_in_channel(event_type, text, chat_id):
            return

        text = self._strip_bot_mention(text)

        thread_ts = event.get("thread_ts")
        if self.config.reply_in_thread and not thread_ts:
            thread_ts = event.get("ts")
        # Add :eyes: reaction to the triggering message (best-effort)
        try:
            if self._web_client and event.get("ts"):
                await self._web_client.reactions_add(
                    channel=chat_id,
                    name=self.config.react_emoji,
                    timestamp=event.get("ts"),
                )
        except Exception as e:
            logger.debug("Slack reactions_add failed: {}", e)

        # Thread-scoped session key for channel/group messages
        session_key = f"slack:{chat_id}:{thread_ts}" if thread_ts and channel_type != "im" else None

        # Extract media from file_share events
        media_paths: list[str] = []
        content_parts: list[str] = []
        if text:
            content_parts.append(text)

        if subtype == "file_share":
            files = event.get("files") or []
            for file_info in files:
                media_path, content_addition = await self._process_slack_file(file_info)
                if media_path:
                    media_paths.append(media_path)
                if content_addition:
                    content_parts.append(content_addition)

        final_content = "\n".join(content_parts) if content_parts else "[empty message]"

        try:
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=final_content,
                media=media_paths,
                metadata={
                    "slack": {
                        "event": event,
                        "thread_ts": thread_ts,
                        "channel_type": channel_type,
                    },
                },
                session_key=session_key,
            )
        except Exception:
            logger.exception("Error handling Slack message from {}", sender_id)

    async def _update_react_emoji(self, chat_id: str, ts: str | None) -> None:
        """Remove the in-progress reaction and optionally add a done reaction."""
        if not self._web_client or not ts:
            return
        try:
            await self._web_client.reactions_remove(
                channel=chat_id,
                name=self.config.react_emoji,
                timestamp=ts,
            )
        except Exception as e:
            logger.debug("Slack reactions_remove failed: {}", e)
        if self.config.done_emoji:
            try:
                await self._web_client.reactions_add(
                    channel=chat_id,
                    name=self.config.done_emoji,
                    timestamp=ts,
                )
            except Exception as e:
                logger.debug("Slack done reaction failed: {}", e)

    async def _process_slack_file(self, file_info: dict) -> tuple[str | None, str | None]:
        """
        Process a Slack file: download media and transcribe if audio.

        Returns:
            tuple: (media_path or None, content_addition or None)
        """
        if not self._web_client:
            return None, None

        file_id = file_info.get("id", "")
        filetype = file_info.get("filetype", "")
        filename = file_info.get("name", "slack_file")
        size = file_info.get("size", 0)
        url_private = file_info.get("url_private_download")

        # Check file size limit
        if size > self.config.max_file_size:
            logger.warning("Slack file too large ({}MB), skipping: {}", size / 1024 / 1024, filename)
            return None, f"[📎 {filename} - 文件过大]"

        if not url_private:
            return None, None

        # Supported image types
        image_types = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}
        # Supported audio types
        audio_types = {"mp3", "m4a", "wav", "ogg", "flac", "aac", "webm"}

        if filetype not in image_types and filetype not in audio_types:
            logger.debug("Skipping unsupported file type: {}", filetype)
            return None, f"[📎 {filename} - 不支持的格式]"

        # Download with retry and timeout
        media_path = await self._download_with_retry(file_id, filename, url_private)
        if not media_path:
            return None, f"[📎 {filename} - 下载失败]"

        # Handle audio transcription
        if filetype in audio_types:
            transcription = await self.transcribe_audio(media_path)
            if transcription:
                logger.info("Transcribed audio {}: {}...", filename, transcription[:50])
                return media_path, f"[🎤 音频转录: {transcription}]"
            return media_path, f"[🎤 音频: {filename}]"

        # Handle images
        if filetype in image_types:
            return media_path, f"[🖼️ 图片: {media_path}]"

        return None, None

    async def _download_with_retry(
        self, file_id: str, filename: str, url_private: str, max_retries: int = 3
    ) -> str | None:
        """
        Download file from Slack with retry logic and timeout protection.

        Uses httpx with Authorization header to download private Slack files.

        Args:
            file_id: Slack file ID
            filename: Original filename
            url_private: Private download URL
            max_retries: Number of retry attempts

        Returns:
            Local file path or None on failure
        """
        media_dir = get_media_dir("slack")
        media_dir.mkdir(parents=True, exist_ok=True)
        file_path = media_dir / f"{file_id}_{filename}"

        # Prepare authorization header using bot token
        headers = {"Authorization": f"Bearer {self.config.bot_token}"}

        for attempt in range(max_retries):
            try:
                # Use httpx to download with timeout
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(url_private, headers=headers)
                    response.raise_for_status()

                    # Write file
                    with open(file_path, "wb") as f:
                        f.write(response.content)

                    logger.info("Downloaded Slack file: {} as {} (attempt {})", filename, file_path, attempt + 1)
                    return str(file_path)

            except asyncio.TimeoutError:
                logger.warning("Download timeout for {} (attempt {})", filename, attempt + 1)
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))
                    continue
            except httpx.TimeoutException:
                logger.warning("HTTP timeout for {} (attempt {})", filename, attempt + 1)
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))
                    continue
            except httpx.HTTPStatusError as e:
                logger.warning("HTTP error for {} (attempt {}): {}", filename, attempt + 1, e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))
                    continue
            except Exception as e:
                logger.warning("Download failed for {} (attempt {}): {}", filename, attempt + 1, e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))
                    continue

        logger.error("Failed to download {} after {} attempts", filename, max_retries)
        return None

    def _is_allowed(self, sender_id: str, chat_id: str, channel_type: str) -> bool:
        if channel_type == "im":
            if not self.config.dm.enabled:
                return False
            if self.config.dm.policy == "allowlist":
                return sender_id in self.config.dm.allow_from
            return True

        # Group / channel messages
        if self.config.group_policy == "allowlist":
            return chat_id in self.config.group_allow_from
        return True

    def _should_respond_in_channel(self, event_type: str, text: str, chat_id: str) -> bool:
        if self.config.group_policy == "open":
            return True
        if self.config.group_policy == "mention":
            if event_type == "app_mention":
                return True
            return self._bot_user_id is not None and f"<@{self._bot_user_id}>" in text
        if self.config.group_policy == "allowlist":
            return chat_id in self.config.group_allow_from
        return False

    def _strip_bot_mention(self, text: str) -> str:
        if not text or not self._bot_user_id:
            return text
        return re.sub(rf"<@{re.escape(self._bot_user_id)}>\s*", "", text).strip()

    _TABLE_RE = re.compile(r"(?m)^\|.*\|$(?:\n\|[\s:|-]*\|$)(?:\n\|.*\|$)*")
    _CODE_FENCE_RE = re.compile(r"```[\s\S]*?```")
    _INLINE_CODE_RE = re.compile(r"`[^`]+`")
    _LEFTOVER_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
    _LEFTOVER_HEADER_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
    _BARE_URL_RE = re.compile(r"(?<![|<])(https?://\S+)")

    @classmethod
    def _to_mrkdwn(cls, text: str) -> str:
        """Convert Markdown to Slack mrkdwn, including tables."""
        if not text:
            return ""
        text = cls._TABLE_RE.sub(cls._convert_table, text)
        return cls._fixup_mrkdwn(slackify_markdown(text))

    @classmethod
    def _fixup_mrkdwn(cls, text: str) -> str:
        """Fix markdown artifacts that slackify_markdown misses."""
        code_blocks: list[str] = []

        def _save_code(m: re.Match) -> str:
            code_blocks.append(m.group(0))
            return f"\x00CB{len(code_blocks) - 1}\x00"

        text = cls._CODE_FENCE_RE.sub(_save_code, text)
        text = cls._INLINE_CODE_RE.sub(_save_code, text)
        text = cls._LEFTOVER_BOLD_RE.sub(r"*\1*", text)
        text = cls._LEFTOVER_HEADER_RE.sub(r"*\1*", text)
        text = cls._BARE_URL_RE.sub(lambda m: m.group(0).replace("&amp;", "&"), text)

        for i, block in enumerate(code_blocks):
            text = text.replace(f"\x00CB{i}\x00", block)
        return text

    @staticmethod
    def _convert_table(match: re.Match) -> str:
        """Convert a Markdown table to a Slack-readable list."""
        lines = [ln.strip() for ln in match.group(0).strip().splitlines() if ln.strip()]
        if len(lines) < 2:
            return match.group(0)
        headers = [h.strip() for h in lines[0].strip("|").split("|")]
        start = 2 if re.fullmatch(r"[|\s:\-]+", lines[1]) else 1
        rows: list[str] = []
        for line in lines[start:]:
            cells = [c.strip() for c in line.strip("|").split("|")]
            cells = (cells + [""] * len(headers))[: len(headers)]
            parts = [f"**{headers[i]}**: {cells[i]}" for i in range(len(headers)) if cells[i]]
            if parts:
                rows.append(" · ".join(parts))
        return "\n".join(rows)
