"""Signal channel implementation using signal-cli JSON-RPC mode."""

import asyncio
import json
import os
from pathlib import Path

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import SignalConfig
from nanobot.utils.helpers import get_extension_from_mime


class SignalChannel(BaseChannel):
    """
    Signal channel using signal-cli JSON-RPC interface.

    Requires signal-cli to be installed and configured:
    1. Install signal-cli: https://github.com/AsamK/signal-cli
    2. Register/link your device: signal-cli link
    3. Configure nanobot with your phone number and optional cli_binary path

    Uses signal-cli in jsonRpc mode with JSON-RPC over stdin/stdout for
    reliable cross-platform message handling.
    """

    name = "signal"

    def __init__(self, config: SignalConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: SignalConfig = config
        self._process: asyncio.subprocess.Process | None = None
        self._receive_task: asyncio.Task | None = None
        self._request_id = 0
        self._response_futures: dict[int, asyncio.Future] = {}

    async def start(self) -> None:
        """Start signal-cli jsonRpc mode and begin listening for messages."""
        if not self.config.phone_number:
            logger.error("Signal phone number not configured")
            return

        cli_path = self.config.cli_binary or "signal-cli"

        # Check if signal-cli is available
        if not await self._check_signal_cli(cli_path):
            logger.error(f"signal-cli not found at {cli_path}")
            return

        self._running = True

        try:
            # Start signal-cli in jsonRpc mode
            cmd = [
                cli_path,
                "--account",
                self.config.phone_number,
                "jsonRpc",
                "--receive-mode",
                "on-start",
            ]

            logger.info(f"Starting Signal channel with account {self.config.phone_number}")

            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Start message receiver task
            self._receive_task = asyncio.create_task(self._receive_loop())

            logger.info("Signal channel started and listening for messages")

            # Keep running until stopped
            while self._running:
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Error starting Signal channel: {e}")
            self._running = False
            raise

    async def stop(self) -> None:
        """Stop signal-cli and cleanup resources."""
        self._running = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._process:
            logger.info("Stopping signal-cli...")
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("signal-cli did not terminate gracefully, killing...")
                self._process.kill()
                await self._process.wait()
            except Exception as e:
                logger.error(f"Error stopping signal-cli: {e}")
            finally:
                self._process = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Signal."""
        if not self._process or not self._running:
            logger.warning("Signal channel not running")
            return

        try:
            recipient = msg.chat_id

            # Handle attachments if present
            attachments = []
            if msg.media:
                for media_path in msg.media:
                    if os.path.exists(media_path):
                        attachments.append(os.path.abspath(media_path))
                    else:
                        logger.warning(f"Attachment not found: {media_path}")

            # Build send command parameters
            params: dict = {
                "recipient": [recipient],
                "message": msg.content,
            }

            if attachments:
                params["attachment"] = attachments

            # Send the message via JSON-RPC
            result = await self._send_jsonrpc("send", params)

            if result and isinstance(result, dict):
                logger.debug(f"Signal message sent to {recipient}")
            else:
                logger.warning(f"Signal send may have failed: {result}")

        except Exception as e:
            logger.error(f"Error sending Signal message: {e}")

    async def _check_signal_cli(self, cli_path: str) -> bool:
        """Check if signal-cli is available and working."""
        try:
            proc = await asyncio.create_subprocess_exec(
                cli_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            return proc.returncode == 0
        except (asyncio.TimeoutError, FileNotFoundError, Exception) as e:
            logger.debug(f"signal-cli check failed: {e}")
            return False

    async def _send_jsonrpc(self, method: str, params: dict | None = None) -> dict | None:
        """Send a JSON-RPC request to signal-cli and await response."""
        if not self._process or not self._process.stdin:
            return None

        self._request_id += 1
        request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": request_id,
        }

        # Create future for response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._response_futures[request_id] = future

        try:
            # Send request
            request_line = json.dumps(request) + "\n"
            self._process.stdin.write(request_line.encode())
            await self._process.stdin.drain()

            # Wait for response with timeout
            return await asyncio.wait_for(future, timeout=30.0)

        except asyncio.TimeoutError:
            logger.warning(f"JSON-RPC request {method} timed out")
            return None
        except Exception as e:
            logger.error(f"Error sending JSON-RPC request: {e}")
            return None
        finally:
            self._response_futures.pop(request_id, None)

    async def _receive_loop(self) -> None:
        """Receive and process messages from signal-cli stdout."""
        if not self._process or not self._process.stdout:
            return

        try:
            while self._running:
                try:
                    line = await asyncio.wait_for(
                        self._process.stdout.readline(),
                        timeout=1.0,
                    )

                    if not line:
                        # EOF reached
                        logger.warning("signal-cli stdout closed")
                        break

                    line_str = line.decode("utf-8", errors="replace").strip()
                    if not line_str:
                        continue

                    # Skip INFO/WARN/ERROR log lines
                    if line_str.startswith(("INFO", "WARN", "ERROR")):
                        logger.debug(f"signal-cli log: {line_str[:100]}")
                        continue

                    await self._handle_jsonrpc_line(line_str)

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error processing signal-cli output: {e}")

        except asyncio.CancelledError:
            logger.debug("Signal receive loop cancelled")
        finally:
            logger.info("Signal receive loop stopped")

    async def _handle_jsonrpc_line(self, line: str) -> None:
        """Handle a single JSON-RPC line from signal-cli."""
        try:
            data = json.loads(line)

            # Handle JSON-RPC responses
            if "id" in data:
                request_id = data.get("id")
                if request_id in self._response_futures:
                    if "result" in data:
                        self._response_futures[request_id].set_result(data["result"])
                    elif "error" in data:
                        error_msg = data["error"].get("message", "Unknown error")
                        logger.warning(f"JSON-RPC error: {error_msg}")
                        self._response_futures[request_id].set_result(None)
                    else:
                        self._response_futures[request_id].set_result(None)
                return

            # Handle incoming messages (notifications)
            if "method" in data:
                method = data.get("method")
                params = data.get("params", {})

                if method == "receive":
                    await self._handle_incoming_message(params)

        except json.JSONDecodeError:
            logger.debug(f"Non-JSON line from signal-cli: {line[:100]}")
        except Exception as e:
            logger.error(f"Error handling JSON-RPC line: {e}")

    async def _handle_incoming_message(self, params: dict) -> None:
        """Handle an incoming Signal message notification."""
        try:
            envelope = params.get("envelope", {})
            if not envelope:
                return

            # Skip sync messages (from ourselves)
            sync_message = envelope.get("syncMessage", {})
            if sync_message:
                return

            # Get data message
            data_message = envelope.get("dataMessage", {})
            if not data_message:
                return

            # Extract message data
            source = envelope.get("source", "")
            source_number = envelope.get("sourceNumber") or source
            source_name = envelope.get("sourceName", "")

            if not source_number:
                logger.debug("Signal message without source number, ignoring")
                return

            # Get message content
            message_text = data_message.get("message", "")
            timestamp = data_message.get("timestamp")

            # Skip empty messages
            if not message_text:
                return

            # Handle attachments
            attachments = data_message.get("attachments", [])
            media_paths = []

            for attachment in attachments:
                try:
                    media_path = await self._download_attachment(attachment)
                    if media_path:
                        media_paths.append(media_path)
                        content_type = attachment.get("contentType", "unknown")
                        message_text += f"\n[attachment: {content_type} - {media_path}]"
                except Exception as e:
                    logger.error(f"Error downloading attachment: {e}")

            # Build sender ID
            sender_id = str(source_number)
            if source_name:
                sender_id = f"{source_number}|{source_name}"

            logger.info(f"Signal message from {sender_id}: {message_text[:50]}...")

            # Forward to message bus
            await self._handle_message(
                sender_id=sender_id,
                chat_id=str(source_number),
                content=message_text.strip(),
                media=media_paths,
                metadata={
                    "timestamp": timestamp,
                    "source_name": source_name,
                    "source_uuid": envelope.get("sourceUuid"),
                },
            )

        except Exception as e:
            logger.error(f"Error handling Signal message: {e}")

    async def _download_attachment(self, attachment: dict) -> str | None:
        """Download an attachment using signal-cli."""
        try:
            attachment_id = attachment.get("id")
            if not attachment_id:
                return None

            # Create media directory
            media_dir = Path.home() / ".nanobot" / "media"
            media_dir.mkdir(parents=True, exist_ok=True)

            # Determine file extension
            content_type = attachment.get("contentType", "application/octet-stream")
            ext = get_extension_from_mime(content_type)

            # Generate filename
            filename = f"signal_{attachment_id}{ext}"
            file_path = media_dir / filename

            # Use JSON-RPC to download attachment
            result = await self._send_jsonrpc(
                "downloadAttachment",
                {"id": attachment_id, "output": str(file_path)},
            )

            if result and file_path.exists():
                logger.debug(f"Downloaded attachment to {file_path}")
                return str(file_path)
            else:
                logger.error(f"Failed to download attachment: {result}")
                return None

        except Exception as e:
            logger.error(f"Error downloading attachment: {e}")
            return None


