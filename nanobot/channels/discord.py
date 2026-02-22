"""Discord channel implementation using Discord Gateway websocket.

Supports:
- Standard text message send/receive via REST API
- A2UI (Agent-to-UI) structured replies → Discord Components V2
- Interactive callbacks (buttons, selects) via Gateway interactions
- Surface state management (create/update/delete stateful UI messages)
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import websockets
from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.discord_a2ui import (
    SurfaceState,
    StructuredReply,
    clear_session_surfaces,
    get_session_id,
    structured_reply_from_text,
)
from nanobot.channels.discord_renderer import (
    build_message_payload,
    _decode_custom_id,
)
from nanobot.config.schema import DiscordConfig


DISCORD_API_BASE = "https://discord.com/api/v10"
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB
MAX_MESSAGE_LEN = 2000  # Discord message character limit


def _split_message(content: str, max_len: int = MAX_MESSAGE_LEN) -> list[str]:
    """Split content into chunks within max_len, preferring line breaks."""
    if not content:
        return []
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        pos = cut.rfind('\n')
        if pos <= 0:
            pos = cut.rfind(' ')
        if pos <= 0:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()
    return chunks


class DiscordChannel(BaseChannel):
    """Discord channel using Gateway websocket with A2UI support."""

    name = "discord"

    def __init__(self, config: DiscordConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: DiscordConfig = config
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._seq: int | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._http: httpx.AsyncClient | None = None

        # A2UI state
        self._surface_states: dict[tuple[str, str], SurfaceState] = {}
        # Maps (session_id, surface_id) → Discord message ID
        self._surface_messages: dict[tuple[str, str], str] = {}
        # Maps Discord message ID → owner user ID (for interaction auth)
        self._interaction_owners: dict[str, str] = {}
        # Stores the last user message per session for "rerun" action
        self._last_user_messages: dict[str, str] = {}

    async def start(self) -> None:
        """Start the Discord gateway connection."""
        if not self.config.token:
            logger.error("Discord bot token not configured")
            return

        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)

        while self._running:
            try:
                logger.info("Connecting to Discord gateway...")
                async with websockets.connect(self.config.gateway_url) as ws:
                    self._ws = ws
                    await self._gateway_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Discord gateway error: {}", e)
                if self._running:
                    logger.info("Reconnecting to Discord gateway in 5 seconds...")
                    await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the Discord channel."""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        for task in self._typing_tasks.values():
            task.cancel()
        self._typing_tasks.clear()
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._http:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Outbound: send messages
    # ------------------------------------------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Discord REST API with A2UI support."""

        if not self._http:
            logger.warning("Discord HTTP client not initialized")
            return

        try:
            is_progress = msg.metadata.get("_progress", False)
            logger.debug("A2UI send: progress={}, content_len={}",
                         is_progress, len(msg.content or ""))

            if is_progress:
                # Progress messages are always plain text
                await self._send_plain_text(msg.chat_id, msg.content, msg.reply_to)
                return

            # Parse content through A2UI pipeline
            session_id = self._session_id_from_metadata(msg.metadata)
            owner_id = msg.metadata.get("owner_id", "")

            structured = structured_reply_from_text(
                msg.content or "", session_id, self._surface_states
            )

            logger.debug(
                "A2UI parsed: a2ui_comps={}, directives={}, ui_intent={}, md_len={}",
                len(structured.a2ui_components),
                len(structured.surface_directives),
                structured.ui_intent is not None,
                len(structured.markdown),
            )

            # Handle surface directives
            if structured.surface_directives:
                logger.info("A2UI: handling {} surface directives", len(structured.surface_directives))
                await self._handle_surface_directives(
                    msg.chat_id, session_id, owner_id, structured
                )
                return

            # Build and send rich message
            if structured.a2ui_components or (structured.ui_intent and structured.ui_intent.buttons):
                logger.info("A2UI: sending rich Components V2 message")
                await self._send_rich_message(
                    msg.chat_id, structured, owner_id, msg.reply_to
                )
            else:
                # Plain text with optional image embeds
                await self._send_text_with_embeds(
                    msg.chat_id, structured, msg.reply_to
                )
        except Exception as e:
            logger.error("Discord send() error: {}", e, exc_info=True)
            # Last-resort fallback: send the PARSED markdown, not the raw JSON
            try:
                fallback_text = structured.markdown if 'structured' in locals() else (msg.content or "")
                await self._send_plain_text(msg.chat_id, fallback_text, msg.reply_to)
            except Exception:
                logger.error("Discord fallback send also failed")
        finally:
            await self._stop_typing(msg.chat_id)

    async def _send_plain_text(
        self, channel_id: str, content: str | None, reply_to: str | None = None
    ) -> None:
        """Send plain text message(s), splitting if necessary."""
        chunks = _split_message(content or "")
        if not chunks:
            return
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        headers = self._auth_headers()
        for i, chunk in enumerate(chunks):
            payload: dict[str, Any] = {"content": chunk}
            if i == 0 and reply_to:
                payload["message_reference"] = {"message_id": reply_to}
                payload["allowed_mentions"] = {"replied_user": False}
            if not await self._send_payload(url, headers, payload):
                break

    async def _send_text_with_embeds(
        self, channel_id: str, structured: StructuredReply, reply_to: str | None = None
    ) -> None:
        """Send text message with optional image embeds."""
        chunks = _split_message(structured.markdown or "")
        if not chunks:
            chunks = [" "]  # avoid empty message

        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        headers = self._auth_headers()

        for i, chunk in enumerate(chunks):
            payload: dict[str, Any] = {"content": chunk}
            if i == 0:
                if reply_to:
                    payload["message_reference"] = {"message_id": reply_to}
                    payload["allowed_mentions"] = {"replied_user": False}
                # Only first chunk gets embeds
                if structured.image_urls:
                    payload["embeds"] = [
                        {"image": {"url": u}} for u in structured.image_urls
                    ]
            if not await self._send_payload(url, headers, payload):
                break

    async def _send_rich_message(
        self, channel_id: str, structured: StructuredReply,
        owner_id: str, reply_to: str | None = None
    ) -> str | None:
        """Send a message with Components V2 or simple buttons.

        Returns the created message ID, or None on failure.
        """
        payload = build_message_payload(structured, owner_id)
        if reply_to:
            payload["message_reference"] = {"message_id": reply_to}
            payload["allowed_mentions"] = {"replied_user": False}

        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        headers = self._auth_headers()

        # Try sending with components
        msg_id = await self._send_payload_return_id(url, headers, payload)
        if msg_id:
            if owner_id:
                self._interaction_owners[msg_id] = owner_id
            return msg_id

        # Fallback: retry without components
        logger.warning("Components V2 send failed, retrying without components")
        fallback: dict[str, Any] = {"content": structured.markdown or " "}
        if reply_to:
            fallback["message_reference"] = {"message_id": reply_to}
            fallback["allowed_mentions"] = {"replied_user": False}
        if structured.image_urls:
            fallback["embeds"] = [
                {"image": {"url": u}} for u in structured.image_urls
            ]
        await self._send_payload(url, headers, fallback)
        return None

    async def _handle_surface_directives(
        self, channel_id: str, session_id: str,
        owner_id: str, structured: StructuredReply
    ) -> None:
        """Route surface directives to create/edit/delete Discord messages."""
        for directive in structured.surface_directives:
            key = (session_id, directive.surface_id)

            if directive.type == "deletesurface":
                msg_id = self._surface_messages.pop(key, None)
                if msg_id:
                    await self._delete_message(channel_id, msg_id)
                    self._interaction_owners.pop(msg_id, None)

            elif directive.type in ("updatecomponents", "updatedatamodel"):
                existing_msg_id = self._surface_messages.get(key)
                if existing_msg_id:
                    # Edit existing message
                    payload = build_message_payload(structured, owner_id)
                    success = await self._edit_message(
                        channel_id, existing_msg_id, payload
                    )
                    if not success:
                        # Fallback: edit without components
                        fallback = {"content": structured.markdown or " "}
                        await self._edit_message(
                            channel_id, existing_msg_id, fallback
                        )
                else:
                    # No existing message — create new
                    msg_id = await self._send_rich_message(
                        channel_id, structured, owner_id
                    )
                    if msg_id:
                        self._surface_messages[key] = msg_id

            elif directive.type == "createsurface":
                # Create new surface message
                msg_id = await self._send_rich_message(
                    channel_id, structured, owner_id
                )
                if msg_id:
                    self._surface_messages[key] = msg_id

    # ------------------------------------------------------------------
    # REST helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bot {self.config.token}"}

    async def _send_payload(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> bool:
        """Send a single Discord API payload with retry on rate-limit. Returns True on success."""
        for attempt in range(3):
            try:
                response = await self._http.post(url, headers=headers, json=payload)
                if response.status_code == 429:
                    data = response.json()
                    retry_after = float(data.get("retry_after", 1.0))
                    logger.warning("Discord rate limited, retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                response.raise_for_status()
                return True
            except Exception as e:
                if attempt == 2:
                    logger.error("Error sending Discord message: {}", e)
                else:
                    await asyncio.sleep(1)
        return False

    async def _send_payload_return_id(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> str | None:
        """Send payload and return the created message ID."""
        for attempt in range(3):
            try:
                response = await self._http.post(url, headers=headers, json=payload)
                if response.status_code == 429:
                    data = response.json()
                    retry_after = float(data.get("retry_after", 1.0))
                    logger.warning("Discord rate limited, retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                if response.status_code >= 400:
                    logger.warning(
                        "Discord API error {}: {}", response.status_code,
                        response.text[:500]
                    )
                    return None
                data = response.json()
                return data.get("id")
            except Exception as e:
                if attempt == 2:
                    logger.error("Error sending Discord message: {}", e)
                else:
                    await asyncio.sleep(1)
        return None

    async def _edit_message(
        self, channel_id: str, message_id: str, payload: dict[str, Any]
    ) -> bool:
        """Edit an existing Discord message via PATCH."""
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}"
        headers = self._auth_headers()
        for attempt in range(3):
            try:
                response = await self._http.patch(url, headers=headers, json=payload)
                if response.status_code == 429:
                    data = response.json()
                    retry_after = float(data.get("retry_after", 1.0))
                    await asyncio.sleep(retry_after)
                    continue
                if response.status_code >= 400:
                    logger.warning(
                        "Discord edit error {}: {}", response.status_code,
                        response.text[:500]
                    )
                    return False
                return True
            except Exception as e:
                if attempt == 2:
                    logger.error("Error editing Discord message: {}", e)
                else:
                    await asyncio.sleep(1)
        return False

    async def _delete_message(self, channel_id: str, message_id: str) -> bool:
        """Delete a Discord message."""
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}"
        headers = self._auth_headers()
        try:
            response = await self._http.delete(url, headers=headers)
            if response.status_code >= 400:
                logger.warning(
                    "Discord delete error {}: {}", response.status_code,
                    response.text[:200]
                )
                return False
            return True
        except Exception as e:
            logger.error("Error deleting Discord message: {}", e)
            return False

    # ------------------------------------------------------------------
    # Gateway: connection lifecycle
    # ------------------------------------------------------------------

    async def _gateway_loop(self) -> None:
        """Main gateway loop: identify, heartbeat, dispatch events."""
        if not self._ws:
            return

        async for raw in self._ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from Discord gateway: {}", raw[:100])
                continue

            op = data.get("op")
            event_type = data.get("t")
            seq = data.get("s")
            payload = data.get("d")

            if seq is not None:
                self._seq = seq

            if op == 10:
                # HELLO: start heartbeat and identify
                interval_ms = payload.get("heartbeat_interval", 45000)
                await self._start_heartbeat(interval_ms / 1000)
                await self._identify()
            elif op == 0 and event_type == "READY":
                logger.info("Discord gateway READY")
            elif op == 0 and event_type == "MESSAGE_CREATE":
                await self._handle_message_create(payload)
            elif op == 0 and event_type == "INTERACTION_CREATE":
                asyncio.create_task(self._handle_interaction_create(payload))
            elif op == 7:
                # RECONNECT: exit loop to reconnect
                logger.info("Discord gateway requested reconnect")
                break
            elif op == 9:
                # INVALID_SESSION: reconnect
                logger.warning("Discord gateway invalid session")
                break

    async def _identify(self) -> None:
        """Send IDENTIFY payload."""
        if not self._ws:
            return

        identify = {
            "op": 2,
            "d": {
                "token": self.config.token,
                "intents": self.config.intents,
                "properties": {
                    "os": "nanobot",
                    "browser": "nanobot",
                    "device": "nanobot",
                },
            },
        }
        await self._ws.send(json.dumps(identify))

    async def _start_heartbeat(self, interval_s: float) -> None:
        """Start or restart the heartbeat loop."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()

        async def heartbeat_loop() -> None:
            while self._running and self._ws:
                payload = {"op": 1, "d": self._seq}
                try:
                    await self._ws.send(json.dumps(payload))
                except Exception as e:
                    logger.warning("Discord heartbeat failed: {}", e)
                    break
                await asyncio.sleep(interval_s)

        self._heartbeat_task = asyncio.create_task(heartbeat_loop())

    # ------------------------------------------------------------------
    # Inbound: message handling
    # ------------------------------------------------------------------

    async def _handle_message_create(self, payload: dict[str, Any]) -> None:
        """Handle incoming Discord messages."""
        author = payload.get("author") or {}
        if author.get("bot"):
            return

        sender_id = str(author.get("id", ""))
        channel_id = str(payload.get("channel_id", ""))
        content = payload.get("content") or ""

        if not sender_id or not channel_id:
            return

        if not self.is_allowed(sender_id):
            return

        content_parts = [content] if content else []
        media_paths: list[str] = []
        media_dir = Path.home() / ".nanobot" / "media"

        for attachment in payload.get("attachments") or []:
            url = attachment.get("url")
            filename = attachment.get("filename") or "attachment"
            size = attachment.get("size") or 0
            if not url or not self._http:
                continue
            if size and size > MAX_ATTACHMENT_BYTES:
                content_parts.append(f"[attachment: {filename} - too large]")
                continue
            try:
                media_dir.mkdir(parents=True, exist_ok=True)
                file_path = media_dir / f"{attachment.get('id', 'file')}_{filename.replace('/', '_')}"
                resp = await self._http.get(url)
                resp.raise_for_status()
                file_path.write_bytes(resp.content)
                media_paths.append(str(file_path))
                content_parts.append(f"[attachment: {file_path}]")
            except Exception as e:
                logger.warning("Failed to download Discord attachment: {}", e)
                content_parts.append(f"[attachment: {filename} - download failed]")

        reply_to = (payload.get("referenced_message") or {}).get("id")
        guild_id = payload.get("guild_id")
        thread_id = None
        # Check if this is a thread
        if payload.get("thread") or (
            payload.get("channel_type") in (10, 11, 12)  # PUBLIC_THREAD, PRIVATE_THREAD, ANNOUNCEMENT_THREAD
        ):
            thread_id = channel_id

        session_id = get_session_id(guild_id, channel_id, sender_id, thread_id)

        # Store last user message for "rerun" action
        user_content = "\n".join(p for p in content_parts if p) or "[empty message]"
        self._last_user_messages[session_id] = user_content

        # Handle /reset command
        if content.strip().lower() == "/reset":
            clear_session_surfaces(session_id, self._surface_states)
            # Clean up surface messages
            to_remove = [k for k in self._surface_messages if k[0] == session_id]
            for k in to_remove:
                msg_id = self._surface_messages.pop(k, None)
                if msg_id:
                    await self._delete_message(channel_id, msg_id)
                    self._interaction_owners.pop(msg_id, None)

        await self._start_typing(channel_id)

        await self._handle_message(
            sender_id=sender_id,
            chat_id=channel_id,
            content=user_content,
            media=media_paths,
            metadata={
                "message_id": str(payload.get("id", "")),
                "guild_id": guild_id,
                "reply_to": reply_to,
                "owner_id": sender_id,
                "session_id": session_id,
            },
        )

    # ------------------------------------------------------------------
    # Interactions: button/select callbacks
    # ------------------------------------------------------------------

    async def _handle_interaction_create(self, payload: dict[str, Any]) -> None:
        """Handle Discord interaction (button click, select menu)."""
        interaction_type = payload.get("type")
        if interaction_type != 3:  # MESSAGE_COMPONENT
            return

        interaction_id = payload.get("id")
        interaction_token = payload.get("token")
        if not interaction_id or not interaction_token:
            return

        # Immediately ACK the interaction (deferred update)
        await self._ack_interaction(interaction_id, interaction_token)

        # Extract interaction details
        comp_data = payload.get("data") or {}
        custom_id = comp_data.get("custom_id") or ""
        component_type = comp_data.get("component_type", 0)

        owner_id, action, payload_hash = _decode_custom_id(custom_id)

        # Owner-only enforcement
        user = payload.get("member", {}).get("user") or payload.get("user") or {}
        actor_id = str(user.get("id", ""))

        if owner_id and actor_id != owner_id:
            # Send ephemeral rejection
            await self._send_followup(
                interaction_token,
                "⛔ Only the original user can interact with these controls.",
                ephemeral=True,
            )
            return

        channel_id = str(payload.get("channel_id", ""))
        guild_id = payload.get("guild_id")

        # Build action context
        if component_type == 3:  # StringSelect
            selected_values = comp_data.get("values", [])
            action_payload = json.dumps({
                "selected": selected_values,
                "payload": payload_hash or "",
            })
        else:
            action_payload = payload_hash

        # Route actions
        if action == "rerun":
            # Re-prompt agent with last user message
            session_id = get_session_id(guild_id, channel_id, actor_id)
            last_msg = self._last_user_messages.get(session_id, "")
            if last_msg:
                await self._start_typing(channel_id)
                await self._handle_message(
                    sender_id=actor_id,
                    chat_id=channel_id,
                    content=last_msg,
                    metadata={
                        "guild_id": guild_id,
                        "owner_id": actor_id,
                        "session_id": session_id,
                        "interaction_rerun": True,
                    },
                )
        elif action:
            # Build action prompt and re-prompt agent
            session_id = get_session_id(guild_id, channel_id, actor_id)

            # Build surface state summary
            state_summary = {}
            for (sid, surf_id), state in self._surface_states.items():
                if sid == session_id:
                    state_summary[surf_id] = {
                        "data_model": state.data_model,
                        "markdown_preview": state.rendered.markdown[:200],
                    }

            action_prompt = (
                f"UI Action executed: {action}\n"
                f"Payload: {action_payload or 'none'}\n"
                f"Current surface state: {json.dumps(state_summary, ensure_ascii=False)}\n"
                f"Generate a response for this action."
            )

            await self._start_typing(channel_id)
            await self._handle_message(
                sender_id=actor_id,
                chat_id=channel_id,
                content=action_prompt,
                metadata={
                    "guild_id": guild_id,
                    "owner_id": actor_id,
                    "session_id": session_id,
                    "interaction_action": action,
                },
            )

    async def _ack_interaction(self, interaction_id: str, token: str) -> None:
        """Send an immediate ACK (deferred update) to Discord."""
        url = f"{DISCORD_API_BASE}/interactions/{interaction_id}/{token}/callback"
        headers = self._auth_headers()
        # Type 6 = DEFERRED_UPDATE_MESSAGE (no visible response)
        payload = {"type": 6}
        try:
            response = await self._http.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                logger.warning("Interaction ACK failed: {}", response.text[:200])
        except Exception as e:
            logger.error("Error ACKing interaction: {}", e)

    async def _send_followup(
        self, token: str, content: str, ephemeral: bool = False
    ) -> None:
        """Send a followup message to an interaction."""
        url = f"{DISCORD_API_BASE}/webhooks/{self._app_id}/{token}"
        headers = self._auth_headers()
        payload: dict[str, Any] = {"content": content}
        if ephemeral:
            payload["flags"] = 64  # EPHEMERAL
        try:
            await self._http.post(url, headers=headers, json=payload)
        except Exception as e:
            logger.error("Error sending followup: {}", e)

    @property
    def _app_id(self) -> str:
        """Get the application ID (extracted from token or cached)."""
        # The bot token contains the application ID as the first segment
        # Format: base64(app_id).timestamp.hmac
        if not hasattr(self, "_cached_app_id"):
            try:
                import base64
                token_part = self.config.token.split(".")[0]
                # Add padding if needed
                padding = 4 - len(token_part) % 4
                if padding != 4:
                    token_part += "=" * padding
                self._cached_app_id = base64.b64decode(token_part).decode()
            except Exception:
                self._cached_app_id = ""
        return self._cached_app_id

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _session_id_from_metadata(self, metadata: dict[str, Any]) -> str:
        """Extract or build a session ID from outbound message metadata."""
        if "session_id" in metadata:
            return metadata["session_id"]
        guild_id = metadata.get("guild_id")
        chat_id = metadata.get("chat_id", "")
        owner_id = metadata.get("owner_id", "")
        return get_session_id(guild_id, chat_id, owner_id)

    async def _start_typing(self, channel_id: str) -> None:
        """Start periodic typing indicator for a channel."""
        await self._stop_typing(channel_id)

        async def typing_loop() -> None:
            url = f"{DISCORD_API_BASE}/channels/{channel_id}/typing"
            headers = self._auth_headers()
            while self._running:
                try:
                    await self._http.post(url, headers=headers)
                except Exception:
                    pass
                await asyncio.sleep(8)

        self._typing_tasks[channel_id] = asyncio.create_task(typing_loop())

    async def _stop_typing(self, channel_id: str) -> None:
        """Stop typing indicator for a channel."""
        task = self._typing_tasks.pop(channel_id, None)
        if task:
            task.cancel()
