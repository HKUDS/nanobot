"""Slack channel implementation using Socket Mode."""

import asyncio
import re
from typing import Any

from loguru import logger
from slack_sdk.socket_mode.websockets import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import SlackConfig


class SlackChannel(BaseChannel):
    """Slack channel using Socket Mode."""

    name = "slack"

    def __init__(self, config: SlackConfig, bus: MessageBus):
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
            logger.error(f"Unsupported Slack mode: {self.config.mode}")
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
            logger.info(f"Slack bot connected as {self._bot_user_id}")
        except Exception as e:
            logger.warning(f"Slack auth_test failed: {e}")

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
                logger.warning(f"Slack socket close failed: {e}")
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
            # Only reply in thread for channel/group messages; DMs don't use threads
            use_thread = thread_ts and channel_type != "im"
            await self._web_client.chat_postMessage(
                channel=msg.chat_id,
                text=self._convert_markdown(msg.content) or "",
                thread_ts=thread_ts if use_thread else None,
            )
        except Exception as e:
            logger.error(f"Error sending Slack message: {e}")

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

        # Ignore bot/system messages (any subtype = not a normal user message)
        if event.get("subtype"):
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

        thread_ts = event.get("thread_ts") or event.get("ts")
        # Add :eyes: reaction to the triggering message (best-effort)
        try:
            if self._web_client and event.get("ts"):
                await self._web_client.reactions_add(
                    channel=chat_id,
                    name="eyes",
                    timestamp=event.get("ts"),
                )
        except Exception as e:
            logger.debug(f"Slack reactions_add failed: {e}")

        await self._handle_message(
            sender_id=sender_id,
            chat_id=chat_id,
            content=text,
            metadata={
                "slack": {
                    "event": event,
                    "thread_ts": thread_ts,
                    "channel_type": channel_type,
                }
            },
        )

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

    def _convert_markdown(self, text: str) -> str:
        if not text:
            return text
        def convert_formatting(input: str) -> str:
            # Convert italics
            # Step 1: *text* -> _text_
            converted_text = re.sub(
                r"(?m)(^|[^\*])\*([^\*].+?[^\*])\*([^\*]|$)", r"\1_\2_\3", input)
            # Convert bold
            # Step 2.a: **text** -> *text*
            converted_text = re.sub(
                r"(?m)(^|[^\*])\*\*([^\*].+?[^\*])\*\*([^\*]|$)", r"\1*\2*\3", converted_text)
            # Step 2.b: __text__ -> *text*
            converted_text = re.sub(
                r"(?m)(^|[^_])__([^_].+?[^_])__([^_]|$)", r"\1*\2*\3", converted_text)
            # convert bold italics
            # Step 3.a: ***text*** -> *_text_*
            converted_text = re.sub(
                r"(?m)(^|[^\*])\*\*\*([^\*].+?[^\*])\*\*\*([^\*]|$)", r"\1*_\2_*\3", converted_text)
            # Step 3.b - ___text___ -> *_text_*
            converted_text = re.sub(
                r"(?m)(^|[^_])___([^_].+?[^_])___([^_]|$)", r"\1*_\2_*\3", converted_text)
            # Convert strikethrough
            # Step 4: ~~text~~ -> ~text~
            converted_text = re.sub(
                r"(?m)(^|[^~])~~([^~].+?[^~])~~([^~]|$)", r"\1~\2~\3", converted_text)
            # Convert URL formatting
            # Step 6: [text](URL) -> <URL|text>
            converted_text = re.sub(
                r"(?m)(^|[^!])\[(.+?)\]\((http.+?)\)", r"\1<\3|\2>", converted_text)
            # Convert image URL
            # Step 6: ![alt text](URL "title") -> <URL>
            converted_text = re.sub(
                r"[!]\[.+?\]\((http.+?)(?: \".*?\")?\)", r"<\1>", converted_text)
            return converted_text
        def escape_mrkdwn(text: str) -> str:
            return (text.replace('&', '&amp;')
                     .replace('<', '&lt;')
                     .replace('>', '&gt;'))
        def convert_table(match: re.Match) -> str:
            # Slack doesn't support Markdown tables
            # Convert table to bulleted list with sections
            # -- input_md:
            # Some text before the table.
            # | Col1 | Col2 | Col3 |
            # |-----|----------|------|
            # | Row1 - A | Row1 - B | Row1 - C |
            # | Row2 - D | Row2 - E | Row2 - F |
            #
            # Some text after the table.
            # 
            # -- will be converted to:
            # Some text before the table.
            # > *Col1* : Row1 - A
            #   • *Col2*: Row1 - B
            #   • *Col3*: Row1 - C
            # > *Col1* : Row2 - D
            #   • *Col2*: Row2 - E
            #   • *Col3*: Row2 - F
            #
            # Some text after the table.
            
            block = match.group(0).strip()
            lines = [line.strip()
                     for line in block.split('\n') if line.strip()]

            if len(lines) < 2:
                return block

            # 1. Parse Headers from the first line
            # Split by pipe, filtering out empty start/end strings caused by outer pipes
            header_line = lines[0].strip('|')
            headers = [escape_mrkdwn(h.strip())
                       for h in header_line.split('|')]

            # 2. Identify Data Start (Skip Separator)
            data_start_idx = 1
            # If line 2 contains only separator chars (|-: ), skip it
            if len(lines) > 1 and not re.search(r'[^|\-\s:]', lines[1]):
                data_start_idx = 2

            # 3. Process Data Rows
            slack_lines = []
            for line in lines[data_start_idx:]:
                # Clean and split cells
                clean_line = line.strip('|')
                cells = [escape_mrkdwn(c.strip())
                         for c in clean_line.split('|')]

                # Normalize cell count to match headers
                if len(cells) < len(headers):
                    cells += [''] * (len(headers) - len(cells))
                cells = cells[:len(headers)]

                # Skip empty rows
                if not any(cells):
                    continue

                # Key is the first column
                key = cells[0]
                label = headers[0]
                slack_lines.append(
                    f"> *{label}* : {key}" if key else "> *{label}* : --")

                # Sub-bullets for remaining columns
                for i, cell in enumerate(cells[1:], 1):
                    if cell:
                        label = headers[i] if i < len(headers) else "Col"
                        slack_lines.append(f"  • *{label}*: {cell}")

                slack_lines.append("")  # Spacer between items

            return "\n".join(slack_lines).rstrip()

        # (?m) : Multiline mode so ^ matches start of line and $ end of line
        # ^\| : Start of line and a literal pipe
        # .*?\|$ : Rest of the line and a pipe at the end
        # (?:\n(?:\|\:?-{3,}\:?)*?\|$) : A heading line with at least three dashes in each column, pipes, and : e.g. |:---|----|:---:|
        # (?:\n\|.*?\|$)* : Zero or more subsequent lines that ALSO start and end with a pipe
        table_pattern = r'(?m)^\|.*?\|$(?:\n(?:\|\:?-{3,}\:?)*?\|$)(?:\n\|.*?\|$)*'

        input_md = convert_formatting(text)
        return re.sub(table_pattern, convert_table, input_md)
