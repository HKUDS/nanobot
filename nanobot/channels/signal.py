"""Signal channel implementation using signal-cli daemon JSON-RPC interface."""

import asyncio
import json
from collections import deque
from pathlib import Path
from typing import Any, TYPE_CHECKING

import httpx
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import SignalConfig

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager


class SignalChannel(BaseChannel):
    """
    Signal channel using signal-cli daemon via HTTP JSON-RPC interface.

    Requires signal-cli daemon in HTTP mode:
    - signal-cli -a +1234567890 daemon --http localhost:8080

    See https://github.com/AsamK/signal-cli for setup instructions.
    """

    name = "signal"

    def __init__(
        self, config: SignalConfig, bus: MessageBus, session_manager: "SessionManager | None" = None
    ):
        super().__init__(config, bus)
        self.config: SignalConfig = config
        self.session_manager = session_manager
        self._http: httpx.AsyncClient | None = None
        self._request_id = 0
        self._sse_task: asyncio.Task | None = None

        # Rolling message buffer for group context (group_id -> deque of messages)
        # Each message is a dict with: sender_name, sender_number, content, timestamp
        self._group_buffers: dict[str, deque] = {}

    async def start(self) -> None:
        """Start the Signal channel and connect to signal-cli daemon."""
        if not self.config.account:
            logger.error("Signal account not configured")
            return

        self._running = True
        await self._start_http_mode()

    async def _start_http_mode(self) -> None:
        """Start Signal channel using Server-Sent Events for receiving messages."""
        base_url = f"http://{self.config.daemon_host}:{self.config.daemon_port}"

        while self._running:
            try:
                logger.info(f"Connecting to signal-cli daemon at {base_url}...")

                # Create HTTP client
                self._http = httpx.AsyncClient(timeout=60.0, base_url=base_url)

                # Test connection
                try:
                    response = await self._http.get("/api/v1/check")
                    if response.status_code == 200:
                        logger.info("Connected to signal-cli daemon")
                    else:
                        logger.warning(
                            f"signal-cli daemon check returned status {response.status_code}"
                        )
                except Exception as e:
                    raise ConnectionRefusedError(f"signal-cli daemon not responding: {e}")

                # Start SSE receiver in background
                self._sse_task = asyncio.create_task(self._sse_receive_loop())

                # Keep running until stopped
                while self._running:
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except ConnectionRefusedError as e:
                logger.error(
                    f"{e}. Make sure signal-cli daemon is running: "
                    f"signal-cli -a {self.config.account} daemon --http {self.config.daemon_host}:{self.config.daemon_port}"
                )
                if self._running:
                    logger.info("Retrying connection in 10 seconds...")
                    await asyncio.sleep(10)
            except Exception as e:
                logger.error(f"Signal channel error: {e}")
                if self._running:
                    logger.info("Reconnecting to signal-cli daemon in 5 seconds...")
                    await asyncio.sleep(5)
            finally:
                if self._sse_task:
                    self._sse_task.cancel()
                    try:
                        await self._sse_task
                    except asyncio.CancelledError:
                        pass
                    self._sse_task = None
                if self._http:
                    await self._http.aclose()
                    self._http = None

    async def stop(self) -> None:
        """Stop the Signal channel."""
        self._running = False

        # Stop SSE task
        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass

        # Close HTTP client
        if self._http:
            await self._http.aclose()
            self._http = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Signal."""
        try:
            # Prepare send request
            params: dict[str, Any] = {"message": msg.content}

            # Determine if this is a group or direct message
            # chat_id format: phone number (+1234567890), UUID, or group ID (base64)
            # Group IDs are base64 and typically contain "=" padding
            # UUIDs are in format "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            if "=" in msg.chat_id or (len(msg.chat_id) > 40 and not "-" in msg.chat_id):
                # Looks like a base64 group ID
                params["groupId"] = msg.chat_id
            else:
                # Phone number or UUID - both work as recipient
                params["recipient"] = [msg.chat_id]

            # Add attachments if present
            if msg.media:
                params["attachments"] = msg.media

            # Send the message
            response = await self._send_request("send", params)

            if "error" in response:
                logger.error(f"Error sending Signal message: {response['error']}")
            elif "result" in response:
                logger.debug(
                    f"Signal message sent successfully, timestamp: {response['result'].get('timestamp')}"
                )

        except Exception as e:
            logger.error(f"Error sending Signal message: {e}")

    async def _sse_receive_loop(self) -> None:
        """Receive messages via Server-Sent Events (HTTP mode)."""
        if not self._http:
            return

        logger.info("Started Signal message receive loop (SSE)")

        try:
            async with self._http.stream("GET", "/api/v1/events") as response:
                if response.status_code != 200:
                    logger.error(f"SSE connection failed with status {response.status_code}")
                    return

                logger.info("Subscribed to Signal messages via SSE")

                # Buffer for accumulating SSE data across multiple lines
                event_buffer = []

                async for line in response.aiter_lines():
                    if not self._running:
                        break

                    # Debug: log raw SSE lines (except keepalive pings)
                    if line and line != ":":
                        logger.debug(f"SSE line received: {line[:200]}")

                    # SSE format handling
                    if isinstance(line, str):
                        # Empty line signals end of event
                        if not line or line == ":":
                            if event_buffer:
                                # Try to parse the accumulated data
                                data_str = ""
                                try:
                                    data_str = "".join(event_buffer)
                                    data = json.loads(data_str)
                                    logger.debug(f"SSE event parsed: {data}")
                                    await self._handle_receive_notification(data)
                                except json.JSONDecodeError as e:
                                    logger.warning(
                                        f"Invalid JSON in SSE buffer: {e}, data: {data_str[:200]}"
                                    )
                                finally:
                                    event_buffer = []

                        # "data:" line - accumulate it
                        elif line.startswith("data:"):
                            event_buffer.append(line[5:])  # Skip "data:" prefix

                        # "event:" line - just log it (we only care about data)
                        elif line.startswith("event:"):
                            pass  # Ignore event type for now

        except asyncio.CancelledError:
            logger.info("SSE receive loop cancelled")
        except Exception as e:
            logger.error(f"Error in SSE receive loop: {e}")

    async def _handle_receive_notification(self, params: dict[str, Any]) -> None:
        """Handle incoming message notification from signal-cli."""
        logger.debug(f"_handle_receive_notification called with: {params}")
        try:
            # Extract envelope from SSE notification: {"envelope": {...}}
            envelope = params.get("envelope", {})

            logger.debug(f"Extracted envelope: {envelope}")

            if not envelope:
                logger.debug("No envelope found in params")
                return

            # Extract sender information
            source = envelope.get("source") or envelope.get("sourceNumber")
            source_uuid = envelope.get("sourceUuid")
            source_name = envelope.get("sourceName")

            if not source:
                logger.debug("Received message without source, skipping")
                return

            # Build sender_id (prefer number, but include UUID for allowlist flexibility)
            sender_id = source
            if source_uuid:
                sender_id = f"{source}|{source_uuid}"

            # Check different message types
            data_message = envelope.get("dataMessage")
            sync_message = envelope.get("syncMessage")
            typing_message = envelope.get("typingMessage")
            receipt_message = envelope.get("receiptMessage")

            # Ignore receipt messages (delivery/read receipts)
            if receipt_message:
                return

            # Handle data messages (incoming messages from others)
            if data_message:
                await self._handle_data_message(sender_id, source, data_message, source_name)

            # Handle sync messages (messages sent from another device)
            elif sync_message and sync_message.get("sentMessage"):
                sent_msg = sync_message["sentMessage"]
                destination = sent_msg.get("destination") or sent_msg.get("destinationNumber")
                if destination:
                    logger.debug(
                        f"Sync message sent to {destination}: {sent_msg.get('message', '')[:50]}"
                    )

            # Handle typing indicators (silently ignore)
            elif typing_message:
                pass  # Ignore typing indicators

        except Exception as e:
            logger.error(f"Error handling receive notification: {e}")

    async def _handle_data_message(
        self,
        sender_id: str,
        sender_number: str,
        data_message: dict[str, Any],
        sender_name: str | None,
    ) -> None:
        """Handle a data message (text, attachments, etc.)."""
        message_text = data_message.get("message") or ""
        attachments = data_message.get("attachments", [])
        group_info = data_message.get("groupInfo")
        timestamp = data_message.get("timestamp")
        mentions = data_message.get("mentions", [])
        reaction = data_message.get("reaction")

        # Log full data_message for debugging group detection
        logger.debug(
            f"Data message from {sender_number}: "
            f"groupInfo={group_info}, "
            f"groupV2={data_message.get('groupV2')}, "
            f"keys={list(data_message.keys())}"
        )

        # Ignore reaction messages (emoji reactions to messages)
        if reaction:
            logger.debug(f"Ignoring reaction message from {sender_number}: {reaction}")
            return

        # Ignore empty messages (e.g., when bot is added to a group)
        if not message_text and not attachments:
            logger.debug(f"Ignoring empty message from {sender_number}")
            return

        # Determine chat_id (group ID or sender number)
        # Check both groupInfo (v1) and groupV2 (v2) fields for group detection
        group_v2 = data_message.get("groupV2")
        is_group_message = group_info is not None or group_v2 is not None

        if is_group_message:
            # This is a group message
            # Extract group ID from either groupInfo or groupV2
            if group_info:
                chat_id = group_info.get("groupId", sender_number)
            elif group_v2:
                chat_id = group_v2.get("id", sender_number)
            else:
                chat_id = sender_number

            # Add to group message buffer BEFORE checking if we should respond
            # This ensures we capture context even for messages we don't reply to
            self._add_to_group_buffer(
                group_id=chat_id,
                sender_name=sender_name or sender_number,
                sender_number=sender_number,
                message_text=message_text,
                timestamp=timestamp,
            )

            # Check if this is a command FIRST (commands bypass group policy)
            if message_text and message_text.strip().startswith("/"):
                command_handled = await self._handle_command(
                    message_text.strip(), chat_id, sender_id, is_group=True
                )
                if command_handled:
                    return  # Command was handled, don't process further

            # Check if this group is allowed
            if not self._is_allowed(sender_id, chat_id, is_group=True):
                logger.debug(
                    f"Ignoring group message from {chat_id} (policy: {self.config.group.policy})"
                )
                return

            # Check if we should respond to this group message (mention requirement)
            should_respond = self._should_respond_in_group(chat_id, message_text, mentions)

            if not should_respond:
                logger.debug(
                    f"Ignoring group message (require_mention: {self.config.group.require_mention})"
                )
                return
        else:
            # This is a direct message
            chat_id = sender_number

            # Check if this is a command (same as group messages)
            if message_text and message_text.strip().startswith("/"):
                command_handled = await self._handle_command(
                    message_text.strip(), chat_id, sender_id, is_group=False
                )
                if command_handled:
                    return  # Command was handled, don't process further

            # Check if sender is allowed for DMs
            if not self._is_allowed(sender_id, chat_id, is_group=False):
                logger.debug(f"Ignoring DM from {sender_id} (policy: {self.config.dm.policy})")
                return

        # Build content from text and attachments
        content_parts = []
        media_paths = []

        # For group messages, include recent message context
        if is_group_message:
            buffer_context = self._get_group_buffer_context(chat_id)
            if buffer_context:
                content_parts.append(f"[Recent group messages for context:]\n{buffer_context}\n---")

        # Prepend sender name for group messages so history shows who said what
        if message_text:
            # Strip bot mentions from text (for group messages)
            if is_group_message:
                message_text = self._strip_bot_mention(message_text, mentions)
                # Prepend sender name to make it clear who is speaking
                display_name = sender_name or sender_number
                message_text = f"[{display_name}]: {message_text}"
            content_parts.append(message_text)

        # Handle attachments
        if attachments:
            import shutil

            media_dir = Path.home() / ".nanobot" / "media"
            media_dir.mkdir(parents=True, exist_ok=True)

            for attachment in attachments:
                attachment_id = attachment.get("id")
                content_type = attachment.get("contentType", "")
                filename = attachment.get("filename") or f"attachment_{attachment_id}"

                if not attachment_id:
                    continue

                try:
                    # signal-cli stores attachments in ~/.local/share/signal-cli/attachments/
                    source_path = (
                        Path.home() / ".local/share/signal-cli/attachments" / attachment_id
                    )

                    if source_path.exists():
                        # Copy to media directory with sanitized filename
                        safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
                        dest_path = media_dir / f"signal_{safe_filename}"
                        shutil.copy2(source_path, dest_path)
                        media_paths.append(str(dest_path))

                        # Determine media type from content type
                        media_type = content_type.split("/")[0] if "/" in content_type else "file"
                        if media_type not in ("image", "audio", "video"):
                            media_type = "file"

                        content_parts.append(f"[{media_type}: {dest_path}]")
                        logger.debug(f"Downloaded attachment: {filename} -> {dest_path}")
                    else:
                        logger.warning(f"Attachment not found: {source_path}")
                        content_parts.append(f"[attachment: {filename} - not found]")

                except Exception as e:
                    logger.warning(f"Failed to process attachment {filename}: {e}")
                    content_parts.append(f"[attachment: {filename} - error]")

        content = "\n".join(content_parts) if content_parts else "[empty message]"

        logger.debug(f"Signal message from {sender_number}: {content[:50]}...")

        # Forward to message bus
        await self._handle_message(
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            media=media_paths,
            metadata={
                "timestamp": timestamp,
                "sender_name": sender_name,
                "sender_number": sender_number,
                "is_group": is_group_message,
                "group_id": (
                    group_info.get("groupId")
                    if group_info
                    else group_v2.get("id")
                    if group_v2
                    else None
                ),
            },
        )

    def _add_to_group_buffer(
        self,
        group_id: str,
        sender_name: str,
        sender_number: str,
        message_text: str,
        timestamp: int | None,
    ) -> None:
        """
        Add a message to the group's rolling buffer.

        Args:
            group_id: The group ID
            sender_name: Display name of sender
            sender_number: Phone number of sender
            message_text: The message content
            timestamp: Message timestamp
        """
        if self.config.group_message_buffer_size <= 0:
            return

        # Create buffer for this group if it doesn't exist
        if group_id not in self._group_buffers:
            self._group_buffers[group_id] = deque(maxlen=self.config.group_message_buffer_size)

        # Add message to buffer (deque will automatically drop oldest when full)
        self._group_buffers[group_id].append(
            {
                "sender_name": sender_name,
                "sender_number": sender_number,
                "content": message_text,
                "timestamp": timestamp,
            }
        )

        logger.debug(
            f"Added message to group buffer {group_id}: "
            f"{len(self._group_buffers[group_id])}/{self.config.group_message_buffer_size}"
        )

    def _get_group_buffer_context(self, group_id: str) -> str:
        """
        Get formatted context from the group's message buffer.

        Args:
            group_id: The group ID

        Returns:
            Formatted string of recent messages (excluding the current one)
        """
        if group_id not in self._group_buffers:
            return ""

        buffer = self._group_buffers[group_id]
        if len(buffer) <= 1:  # Only current message, no context
            return ""

        # Format all messages except the last one (which is the current message)
        # We want to show context BEFORE the mention
        context_messages = list(buffer)[:-1]  # Exclude the last (current) message

        lines = []
        for msg in context_messages:
            sender = msg["sender_name"]
            content = msg["content"][:200]  # Limit to 200 chars per message
            lines.append(f"{sender}: {content}")

        return "\n".join(lines)

    async def _handle_command(
        self, command_text: str, chat_id: str, sender_id: str, is_group: bool
    ) -> bool:
        """
        Handle slash commands like /reset, /help.

        Args:
            command_text: The command message (e.g., "/reset")
            chat_id: The chat/group ID
            sender_id: The sender's ID
            is_group: Whether this is a group chat

        Returns:
            True if command was handled, False otherwise
        """
        # Check if sender is allowed (respects DM and group policies)
        if not self._is_allowed(sender_id, chat_id, is_group):
            logger.warning(
                f"Command access denied for sender {sender_id} on channel {self.name}. "
                f"Check dm.policy and dm.allow_from (for DMs) or group_policy and group_allow_from (for groups)."
            )
            return False

        # Extract command (first word without /)
        parts = command_text.split()
        if not parts or not parts[0].startswith("/"):
            return False

        command = parts[0][1:].lower()  # Remove / and lowercase

        if command == "reset":
            await self._handle_reset_command(chat_id, sender_id, is_group)
            return True
        elif command == "help":
            await self._handle_help_command(chat_id)
            return True

        return False

    async def _handle_reset_command(self, chat_id: str, sender_id: str, is_group: bool) -> None:
        """Handle /reset command - clear conversation history."""
        if self.session_manager is None:
            logger.warning("/reset called but session_manager is not available")
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=self.name,
                    chat_id=chat_id,
                    content="⚠️ Session management is not available.",
                )
            )
            return

        session_key = f"{self.name}:{chat_id}"
        session = self.session_manager.get_or_create(session_key)
        msg_count = len(session.messages)
        session.clear()
        self.session_manager.save(session)

        logger.info(f"Session reset for {session_key} (cleared {msg_count} messages)")

        response = "🔄 Conversation history cleared. Let's start fresh!"
        await self.bus.publish_outbound(
            OutboundMessage(channel=self.name, chat_id=chat_id, content=response)
        )

    async def _handle_help_command(self, chat_id: str) -> None:
        """Handle /help command - show available commands."""
        help_text = (
            "🐈 nanobot commands\n\n"
            "/reset — Reset conversation history\n"
            "/help — Show this help message\n\n"
            "Just send me a message to chat!"
        )

        await self.bus.publish_outbound(
            OutboundMessage(channel=self.name, chat_id=chat_id, content=help_text)
        )

    def _should_respond_in_group(
        self, chat_id: str, message_text: str, mentions: list[dict[str, Any]]
    ) -> bool:
        """
        Determine if the bot should respond to a group message.

        Args:
            chat_id: The group ID
            message_text: The message text content
            mentions: List of mentions from Signal (format: [{"number": "+1234567890", "start": 0, "length": 10}])

        Returns:
            True if bot should respond, False otherwise
        """
        # Check if mention is required (with backward compatibility)
        # If deprecated group_policy is "open" or "mention", use that; otherwise use group.require_mention
        require_mention = self.config.group.require_mention

        # Backward compatibility: if group_policy is set to "open", don't require mention
        if self.config.group_policy == "open":
            require_mention = False
        # Backward compatibility: if group_policy is "mention", require mention
        elif self.config.group_policy == "mention":
            require_mention = True

        # If mention is not required, respond to all messages
        if not require_mention:
            return True

        # If mention is required, check if bot was mentioned
        if self.config.account:
            # Check if our account number is in the mentions list
            for mention in mentions:
                mentioned_number = mention.get("number") or mention.get("uuid")
                if mentioned_number == self.config.account:
                    return True

            # Fallback: check for phone number in message text (less reliable)
            # Signal mentions format: @+1234567890 or just +1234567890
            if message_text and self.config.account in message_text:
                return True

        return False

    def _strip_bot_mention(self, text: str, mentions: list[dict[str, Any]]) -> str:
        """
        Remove bot mentions from message text.

        Signal mentions are embedded in the text, so we need to remove them based on
        the mentions array which provides start position and length.

        Args:
            text: Original message text
            mentions: List of mention objects with start/length positions

        Returns:
            Text with bot mentions removed
        """
        if not text or not self.config.account:
            return text

        # Build a list of (start, length) tuples for our bot's mentions
        bot_mentions = []
        for mention in mentions:
            mentioned_number = mention.get("number") or mention.get("uuid")
            if mentioned_number == self.config.account:
                start = mention.get("start", 0)
                length = mention.get("length", 0)
                bot_mentions.append((start, length))

        # Sort mentions by start position (descending) to remove from end to start
        # This prevents position shifts when removing earlier mentions
        bot_mentions.sort(reverse=True)

        # Remove each mention
        for start, length in bot_mentions:
            text = text[:start] + text[start + length :]

        return text.strip()

    def _is_allowed(self, sender_id: str, chat_id: str, is_group: bool) -> bool:
        """
        Check if a sender is allowed to interact with the bot.

        Args:
            sender_id: The sender's identifier (phone number or UUID)
            chat_id: The chat/group ID
            is_group: Whether this is a group message

        Returns:
            True if allowed, False otherwise
        """
        if is_group:
            # For groups, check if group itself is enabled and allowed
            if not self.config.group.enabled:
                return False
            if self.config.group.policy == "allowlist":
                # Check new group.allow_from first, fallback to deprecated group_allow_from
                allow_list = self.config.group.allow_from or self.config.group_allow_from
                return chat_id in allow_list
            return True

        # For DMs, check dm policy
        if not self.config.dm.enabled:
            return False
        if self.config.dm.policy == "allowlist":
            # Check sender_id against allowlist
            # Try new dm.allow_from first, fallback to deprecated allow_from
            allow_list = self.config.dm.allow_from or self.config.allow_from
            sender_str = str(sender_id)
            if sender_str in allow_list:
                return True
            # Also check individual parts if sender_id contains "|" (number|uuid format)
            if "|" in sender_str:
                for part in sender_str.split("|"):
                    if part and part in allow_list:
                        return True
            return False
        return True

    async def _send_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a JSON-RPC request via HTTP and wait for response."""
        # Generate request ID
        self._request_id += 1
        request_id = self._request_id

        # Build JSON-RPC request
        request = {"jsonrpc": "2.0", "method": method, "id": request_id}

        if params:
            request["params"] = params

        return await self._send_http_request(request)

    async def _send_http_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send JSON-RPC request via HTTP."""
        if not self._http:
            raise RuntimeError("Not connected to signal-cli daemon")

        try:
            response = await self._http.post("/api/v1/rpc", json=request)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"HTTP request failed: {e}")
            return {"error": {"message": str(e)}}
