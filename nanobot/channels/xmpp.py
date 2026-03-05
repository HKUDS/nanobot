"""XMPP channel — MUC room and direct message support."""

import asyncio
from typing import Any

from loguru import logger

try:
    from slixmpp import ClientXMPP
    from slixmpp.exceptions import XMPPError
except ImportError as e:
    raise ImportError(
        "XMPP dependencies not installed. Run: pip install slixmpp"
    ) from e

from nanobot.bus.events import OutboundMessage
from nanobot.channels.base import BaseChannel


class XmppClient(ClientXMPP):
    """XMPP client wrapper with MUC support."""

    def __init__(
        self,
        jid: str,
        password: str,
        channel: "XmppChannel",
        nickname: str = "nanobot",
        rooms: list[str] | None = None,
    ):
        super().__init__(jid, password)
        self._channel = channel
        self._nickname = nickname
        self._rooms = set(rooms or [])
        self._joined_rooms: set[str] = set()
        self._running = False

        # Register plugins
        self.register_plugin("xep_0030")  # Service Discovery
        self.register_plugin("xep_0045")  # MUC
        self.register_plugin("xep_0085")  # Chat State Notifications (typing)
        self.register_plugin("xep_0096")  # File Transfer (placeholder for future)

        # Event handlers
        self.add_event_handler("session_start", self._on_session_start)
        self.add_event_handler("message", self._on_message)
        self.add_event_handler("disconnected", self._on_disconnected)

    async def _on_session_start(self, event: Any) -> None:
        """Handle session start - send presence and join rooms."""
        logger.info("XMPP session started for {}", self.boundjid)
        self.send_presence()
        logger.debug("Presence sent")
        await self.get_roster()
        logger.debug("Roster retrieved: {} contacts", len(self.client_roster))

        # Join configured MUC rooms
        for room in self._rooms:
            try:
                self.plugin["xep_0045"].join_muc(room, self._nickname)
                self._joined_rooms.add(room)
                logger.info("Joined XMPP room: {}", room)
            except Exception as e:
                logger.warning("Failed to join XMPP room {}: {}", room, e)

    def _on_message(self, msg: Any) -> None:
        """Handle incoming messages."""
        msg_type = msg.get("type", "unknown")
        msg_from = str(msg["from"])
        msg_body = str(msg["body"]) if msg["body"] else ""

        logger.debug("Message received: type={} from={} body={!r}", msg_type, msg_from, msg_body[:50] if msg_body else "")

        # Ignore messages from ourselves to prevent loops
        if str(msg["from"].bare) == self.boundjid.bare:
            logger.debug("Ignoring message from self")
            return

        if not msg_body.strip():
            logger.debug("Ignoring message with empty body")
            return

        if msg_type in ("chat", "normal"):
            # Direct message - use bare JID for typing to handle multi-resource clients
            bare_jid = str(msg["from"].bare)
            logger.info("Direct message from {}: {}", msg_from, msg_body[:100] if msg_body else "")
            asyncio.create_task(self._channel._handle_dm(
                sender_jid=bare_jid,
                body=msg_body,
            ))
        elif msg_type == "groupchat":
            # MUC message
            logger.info("MUC message from {} in {}: {}", msg["from"].resource, msg["from"].bare, msg_body[:100] if msg_body else "")
            asyncio.create_task(self._channel._handle_muc_message(
                room_jid=str(msg["from"].bare),
                sender_nick=str(msg["from"].resource),
                sender_jid=str(msg["from"]),
                body=msg_body,
            ))
        else:
            logger.debug("Ignoring message with type: {}", msg_type)

    def _on_disconnected(self, event: Any) -> None:
        """Handle disconnection."""
        logger.warning("XMPP disconnected, will reconnect...")
        self._joined_rooms.clear()
        
        # Cancel and clear typing tasks to prevent memory leaks and orphaned tasks
        for task in self._channel._typing_tasks.values():
            task.cancel()
        self._channel._typing_tasks.clear()

    def send_typing(self, to_jid: str, typing: bool = True) -> None:
        """Send typing notification."""
        state = "composing" if typing else "paused"
        msg = self.make_message(mto=to_jid, mtype="chat")
        msg["chat_state"] = state
        msg.send()

    def shutdown(self) -> None:
        """Clean shutdown."""
        self._running = False
        self.disconnect()


class XmppChannel(BaseChannel):
    """XMPP channel supporting direct messages and MUC rooms."""

    name = "xmpp"

    def __init__(self, config: Any, bus: Any):
        super().__init__(config, bus)
        self.client: XmppClient | None = None
        self._task: asyncio.Task | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        """Start XMPP client and connect to server."""
        self._running = True

        # Build room list from config
        rooms = list(getattr(self.config, "rooms", []) or [])

        self.client = XmppClient(
            jid=self.config.jid,
            password=self.config.password,
            channel=self,
            nickname=getattr(self.config, "nickname", "nanobot"),
            rooms=rooms,
        )

        # Configure TLS
        self.client.use_ssl = getattr(self.config, "use_tls", True)
        if hasattr(self.config, "server") and self.config.server:
            self.client.connect_address = (self.config.server, self.config.port)

        self.client._running = True
        self._task = asyncio.create_task(self._run_client())
        logger.info("XMPP channel started for {}", self.config.jid)

    async def _run_client(self) -> None:
        """Run the XMPP client with reconnection logic."""
        while self._running:
            try:
                await self.client.connect()
                # Keep the task alive until disconnected
                while self.client.is_connected() and self._running:
                    await asyncio.sleep(1)
            except Exception as e:
                logger.warning("XMPP connection error: {}", e)
            if self._running:
                await asyncio.sleep(5)  # Reconnect delay

    async def stop(self) -> None:
        """Stop the XMPP channel."""
        self._running = False

        # Cancel typing tasks
        for task in self._typing_tasks.values():
            task.cancel()
        self._typing_tasks.clear()

        if self.client:
            self.client.shutdown()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def send(self, msg: OutboundMessage) -> None:
        """Send an outbound message."""
        if not self.client or not self.client.is_connected():
            logger.warning("XMPP not connected, cannot send message")
            return

        # Stop typing indicator if active
        await self._stop_typing(msg.chat_id)

        content = msg.content or ""
        self.client.send_message(msg.chat_id, content, mtype="chat")

    async def _handle_dm(self, sender_jid: str, body: str) -> None:
        """Handle direct message."""
        if not body.strip():
            return

        # Start typing indicator
        await self._start_typing(sender_jid)

        try:
            await self._handle_message(
                sender_id=sender_jid,
                chat_id=sender_jid,
                content=body,
                metadata={"type": "direct", "jid": sender_jid},
            )
        except Exception:
            await self._stop_typing(sender_jid)
            raise

    async def _handle_muc_message(
        self, room_jid: str, sender_nick: str, sender_jid: str, body: str
    ) -> None:
        """Handle MUC (groupchat) message."""
        if not body.strip():
            return

        # Skip messages from ourselves
        if sender_nick == getattr(self.config, "nickname", "nanobot"):
            return

        # Check if we should process this message based on group policy
        if not self._should_process_muc_message(room_jid, body):
            return

        # Start typing indicator
        await self._start_typing(room_jid)

        try:
            await self._handle_message(
                sender_id=f"{room_jid}/{sender_nick}",
                chat_id=room_jid,
                content=body,
                metadata={
                    "type": "muc",
                    "room": room_jid,
                    "sender_nick": sender_nick,
                    "sender_jid": sender_jid,
                },
            )
        except Exception:
            await self._stop_typing(room_jid)
            raise

    def _should_process_muc_message(self, room_jid: str, body: str) -> bool:
        """Apply group policy checks for MUC messages."""
        policy = getattr(self.config, "group_policy", "open")

        if policy == "open":
            return True

        if policy == "allowlist":
            allowed = getattr(self.config, "group_allow_from", []) or []
            return room_jid in allowed

        if policy == "mention":
            nickname = getattr(self.config, "nickname", "nanobot")
            # Check if bot nickname is mentioned
            return f"@{nickname}" in body or nickname in body.split()

        return True

    async def _start_typing(self, jid: str) -> None:
        """Start typing indicator with keepalive."""
        await self._stop_typing(jid)

        if self.client and self.client.is_connected():
            try:
                self.client.send_typing(jid, typing=True)
            except Exception:
                pass

        # Start keepalive task
        async def keepalive():
            try:
                while self._running:
                    await asyncio.sleep(25)  # Refresh typing every 25s
                    if self.client and self.client.is_connected():
                        try:
                            self.client.send_typing(jid, typing=True)
                        except Exception:
                            break
            except asyncio.CancelledError:
                pass

        self._typing_tasks[jid] = asyncio.create_task(keepalive())

    async def _stop_typing(self, jid: str) -> None:
        """Stop typing indicator."""
        if jid in self._typing_tasks:
            task = self._typing_tasks.pop(jid)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        if self.client and self.client.is_connected():
            try:
                # Send "paused" to indicate stopped typing
                self.client.send_typing(jid, typing=False)
                # After a brief delay, send "active" to clear the indicator entirely
                await asyncio.sleep(0.5)
                if self.client and self.client.is_connected():
                    msg = self.client.make_message(mto=jid, mtype="chat")
                    msg["chat_state"] = "active"
                    msg.send()
            except Exception:
                pass
