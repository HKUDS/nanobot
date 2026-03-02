"""iMessage channel implementation using imsg JSON-RPC 2.0 over stdio."""

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import iMessageConfig


class iMessageChannel(BaseChannel):
    """
    iMessage channel using the imsg CLI tool.

    Spawns `imsg rpc` as a subprocess and communicates via JSON-RPC 2.0
    over stdin/stdout for bidirectional iMessage communication.
    """

    name = "imessage"

    def __init__(self, config: iMessageConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: iMessageConfig = config
        self._process: asyncio.subprocess.Process | None = None
        self._rpc_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._subscription_id: str | None = None
        self._reader_task: asyncio.Task | None = None
        # Track sent message IDs for self-chat loop prevention
        self._sent_message_ids: set[str] = set()
        # Track text of bot-sent replies to catch echoes with different IDs
        self._sent_texts: dict[str, float] = {}  # "chat_id:text" -> timestamp
        # Dedup: track numeric IDs of messages we've already dispatched
        self._seen_ids: dict[int, float] = {}  # numeric msg id -> timestamp

    def _get_imsg_path(self) -> str:
        """Resolve path to the imsg binary."""
        if self.config.imsg_path:
            expanded = str(Path(self.config.imsg_path).expanduser())
            if Path(expanded).is_file():
                return expanded
        # Auto-detect from PATH
        found = shutil.which("imsg")
        if found:
            return found
        # Common location
        home_path = Path.home() / "Code" / "imsg" / "bin" / "imsg"
        if home_path.is_file():
            return str(home_path)
        raise FileNotFoundError(
            "imsg binary not found. Set imsg_path in config or add imsg to PATH."
        )

    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    async def _send_rpc(self, method: str, params: dict | None = None) -> Any:
        """Send a JSON-RPC 2.0 request and wait for the response."""
        if not self._process or not self._process.stdin:
            raise RuntimeError("imsg process not running")

        rpc_id = self._next_id()
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        line = json.dumps(request) + "\n"
        logger.debug(f"iMessage RPC >> {method}(id={rpc_id}) params={params}")
        self._process.stdin.write(line.encode())
        await self._process.stdin.drain()

        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending[rpc_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=30.0)
            logger.debug(f"iMessage RPC << {method}(id={rpc_id}) result={result}")
            return result
        except asyncio.TimeoutError:
            self._pending.pop(rpc_id, None)
            logger.warning(f"iMessage RPC timeout for {method}(id={rpc_id})")
            raise

    async def _read_stdout(self) -> None:
        """Read lines from imsg stdout and dispatch responses/notifications."""
        assert self._process and self._process.stdout
        while True:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    logger.warning("imsg process stdout closed")
                    break

                text = line.decode().strip()
                if not text:
                    continue

                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    logger.debug(f"imsg non-JSON output: {text[:200]}")
                    continue

                if "id" in data and data["id"] in self._pending:
                    # RPC response
                    future = self._pending.pop(data["id"])
                    if "error" in data:
                        future.set_exception(
                            RuntimeError(f"RPC error: {data['error']}")
                        )
                    else:
                        future.set_result(data.get("result"))
                elif "method" in data:
                    # RPC notification
                    await self._handle_rpc_notification(data)
                else:
                    logger.debug(f"imsg unknown message: {text[:200]}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error reading imsg stdout: {e}")
                await asyncio.sleep(0.1)

    async def _handle_rpc_notification(self, data: dict) -> None:
        """Handle a JSON-RPC notification from imsg."""
        method = data.get("method", "")
        params = data.get("params", {})
        logger.debug(f"iMessage notification method={method} raw_data_keys={list(data.keys())}")

        if method == "message":
            await self._handle_incoming_message(params)
        else:
            logger.debug(f"imsg notification: {method}")

    async def _handle_incoming_message(self, params: dict) -> None:
        """Process an incoming iMessage."""
        import time

        # The message data is nested inside params["message"]
        msg = params.get("message", params)
        is_from_me = msg.get("is_from_me", False)
        msg_guid = str(msg.get("guid", ""))
        msg_numeric_id = msg.get("id")

        sender = msg.get("sender", "")
        text = msg.get("text", "")
        chat_guid = msg.get("chat_guid", "")
        is_group = msg.get("is_group", False)

        logger.info(
            f"iMessage incoming: from={sender} is_from_me={is_from_me} "
            f"is_group={is_group} id={msg_numeric_id} guid={msg_guid} "
            f"text={text[:80]!r}"
        )

        if not text:
            logger.debug(f"iMessage skipping empty message guid={msg_guid}")
            return

        # Dedup by numeric ID — iMessage delivers each self-chat message
        # multiple times with different GUIDs but sequential numeric IDs.
        # Skip if we already processed a message with close numeric ID and
        # identical text.
        if msg_numeric_id is not None:
            now = time.monotonic()
            if msg_numeric_id in self._seen_ids:
                logger.debug(
                    f"iMessage skipping duplicate numeric id={msg_numeric_id} "
                    f"guid={msg_guid}"
                )
                return
            # Also check id-1: the echo pair often has consecutive IDs
            if (msg_numeric_id - 1) in self._seen_ids:
                logger.debug(
                    f"iMessage skipping echo (consecutive id={msg_numeric_id}, "
                    f"prev={msg_numeric_id - 1}) guid={msg_guid}"
                )
                return

        # Use chat_guid for groups, sender phone for DMs
        chat_id = chat_guid if is_group and chat_guid else sender

        # Check if this text matches a recent bot reply
        sent_key = f"{chat_id}:{text}"
        if sent_key in self._sent_texts:
            elapsed = time.monotonic() - self._sent_texts[sent_key]
            if elapsed < 120:
                logger.debug(
                    f"iMessage skipping bot reply echo "
                    f"(sent {elapsed:.1f}s ago) guid={msg_guid}"
                )
                return
            else:
                del self._sent_texts[sent_key]

        if self.config.self_chat:
            # Self-chat mode: only process is_from_me=true (skip the echo duplicate)
            if not is_from_me:
                logger.debug(
                    f"iMessage skipping echo (is_from_me=false in self_chat mode) "
                    f"guid={msg_guid}"
                )
                return
            logger.info(f"iMessage self-chat: processing own message guid={msg_guid}")
        else:
            # Normal mode: skip all own messages
            if is_from_me:
                logger.debug(f"iMessage skipping fromMe message (self_chat disabled)")
                return

        # Record this message's numeric ID so its echo is skipped
        if msg_numeric_id is not None:
            self._seen_ids[msg_numeric_id] = time.monotonic()
            asyncio.get_event_loop().call_later(
                120, self._seen_ids.pop, msg_numeric_id, None
            )

        sender_id = sender

        # Build media list from attachments
        media: list[str] = []
        for att in msg.get("attachments", []):
            path = att.get("original_path") or att.get("path", "")
            if path:
                media.append(path)

        logger.info(
            f"iMessage dispatching: sender_id={sender_id} chat_id={chat_id} "
            f"media={len(media)} files"
        )

        await self._handle_message(
            sender_id=sender_id,
            chat_id=chat_id,
            content=text,
            media=media or None,
            metadata={
                "message_id": msg_guid,
                "is_group": is_group,
                "chat_guid": chat_guid,
            },
        )

    async def start(self) -> None:
        """Start the iMessage channel by spawning imsg rpc."""
        imsg_path = self._get_imsg_path()
        logger.info(f"Starting iMessage channel with imsg at {imsg_path}")
        logger.info(f"iMessage config: self_chat={self.config.self_chat} allow_from={self.config.allow_from}")

        self._running = True

        while self._running:
            try:
                self._process = await asyncio.create_subprocess_exec(
                    imsg_path,
                    "rpc",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                logger.info(f"imsg rpc process started (pid={self._process.pid})")

                # Start reading stdout
                self._reader_task = asyncio.create_task(self._read_stdout())

                # Subscribe to all incoming messages (no chat_id filter = all chats)
                try:
                    result = await self._send_rpc("watch.subscribe")
                    if isinstance(result, dict):
                        self._subscription_id = result.get("subscription_id")
                    logger.info("Subscribed to iMessage notifications")
                except Exception as e:
                    logger.error(f"Failed to subscribe to iMessage: {e}")

                # Wait for the reader task (runs until process exits)
                await self._reader_task

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"iMessage channel error: {e}")

            # Cleanup before reconnect
            await self._cleanup_process()

            if self._running:
                logger.info("Restarting imsg rpc in 5 seconds...")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the iMessage channel."""
        logger.info("Stopping iMessage channel...")
        self._running = False

        # Unsubscribe
        if self._subscription_id and self._process and self._process.stdin:
            try:
                await self._send_rpc(
                    "watch.unsubscribe",
                    {"subscription_id": self._subscription_id},
                )
            except Exception:
                pass

        await self._cleanup_process()

    async def _cleanup_process(self) -> None:
        """Clean up the imsg subprocess."""
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
            self._process = None

        self._pending.clear()
        self._subscription_id = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through iMessage."""
        if not self._process or not self._process.stdin:
            logger.warning("iMessage channel not connected")
            return

        try:
            import time

            # Track sent text BEFORE sending so echoes arriving during the
            # await are already filtered (race condition fix)
            sent_key = f"{msg.chat_id}:{msg.content}"
            self._sent_texts[sent_key] = time.monotonic()
            asyncio.get_event_loop().call_later(
                120, self._sent_texts.pop, sent_key, None
            )

            logger.info(f"iMessage sending to={msg.chat_id} text={msg.content[:80]!r}")
            result = await self._send_rpc("send", {"to": msg.chat_id, "text": msg.content})
            logger.info(f"iMessage sent successfully to={msg.chat_id}")

            # Also track sent message ID if available
            if isinstance(result, dict) and result.get("id"):
                sent_id = str(result["id"])
                self._sent_message_ids.add(sent_id)
                logger.debug(f"iMessage tracking sent id={sent_id} for loop prevention")
                asyncio.get_event_loop().call_later(
                    120, self._sent_message_ids.discard, sent_id
                )
        except Exception as e:
            logger.error(f"Error sending iMessage: {e}")
