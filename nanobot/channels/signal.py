"""Signal channel implementation using signal-cli JSON-RPC."""

import asyncio
import json

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import SignalConfig


class SignalChannel(BaseChannel):
    """Signal channel using signal-cli's JSON-RPC interface (stdin/stdout)."""

    name = "signal"

    def __init__(self, config: SignalConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: SignalConfig = config
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._rpc_id = 0

    async def start(self) -> None:
        """Start signal-cli in JSON-RPC mode and listen for messages."""
        if not self.config.phone_number:
            logger.error("Signal phone_number not configured")
            return

        self._running = True

        try:
            self._process = await asyncio.create_subprocess_exec(
                self.config.signal_cli_path,
                "-a", self.config.phone_number,
                "jsonRpc",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.error(
                f"signal-cli not found at '{self.config.signal_cli_path}'. "
                "Install: https://github.com/AsamK/signal-cli"
            )
            self._running = False
            return
        except Exception as e:
            logger.error(f"Failed to start signal-cli: {e}")
            self._running = False
            return

        self._reader_task = asyncio.create_task(self._read_stdout())
        asyncio.create_task(self._log_stderr())
        logger.info(f"Signal channel started for {self.config.phone_number}")

    async def stop(self) -> None:
        """Stop signal-cli process."""
        self._running = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None
        logger.info("Signal channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message via signal-cli JSON-RPC."""
        if not self._process or not self._process.stdin:
            logger.warning("Signal process not running")
            return

        self._rpc_id += 1

        # Determine if chat_id is a group or individual
        params: dict = {"message": msg.content}
        if msg.chat_id.startswith("group."):
            params["groupId"] = msg.chat_id.removeprefix("group.")
        else:
            params["recipient"] = [msg.chat_id]

        request = {
            "jsonrpc": "2.0",
            "method": "send",
            "id": self._rpc_id,
            "params": params,
        }

        try:
            line = json.dumps(request) + "\n"
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()
        except Exception as e:
            logger.error(f"Error sending Signal message: {e}")

    async def _read_stdout(self) -> None:
        """Read JSON-RPC responses and notifications from signal-cli stdout."""
        assert self._process and self._process.stdout

        while self._running:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    if self._running:
                        logger.warning("signal-cli process ended unexpectedly")
                    break

                raw = line.decode().strip() if isinstance(line, bytes) else line.strip()
                logger.debug(f"signal-cli stdout: {raw[:500]}")
                data = json.loads(raw)
                await self._handle_jsonrpc(data)
            except json.JSONDecodeError as e:
                logger.debug(f"signal-cli non-JSON line: {line!r}")
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error reading signal-cli output: {e}")

    async def _handle_jsonrpc(self, data: dict) -> None:
        """Handle a JSON-RPC message from signal-cli."""
        method = data.get("method")

        if method == "receive":
            await self._on_receive(data.get("params", {}))
        elif method:
            logger.debug(f"signal-cli unhandled method: {method}")
        elif "id" in data:
            # JSON-RPC response to a request we sent (e.g. send result)
            if "error" in data:
                logger.error(f"signal-cli RPC error: {data['error']}")
            else:
                logger.debug(f"signal-cli RPC response id={data['id']}")

    async def _trust_identity(self, source: str) -> None:
        """Auto-trust a sender's new identity key via JSON-RPC."""
        self._rpc_id += 1
        request = {
            "jsonrpc": "2.0",
            "method": "trust",
            "id": self._rpc_id,
            "params": {"recipient": source, "trustAllKnownKeys": True},
        }
        try:
            line = json.dumps(request) + "\n"
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()
            logger.info(f"Auto-trusted new identity for {source}")
        except Exception as e:
            logger.error(f"Failed to auto-trust {source}: {e}")

    async def _on_receive(self, params: dict) -> None:
        """Handle an incoming Signal message."""
        envelope = params.get("envelope", {})
        source = envelope.get("sourceNumber", "")
        if not source:
            return

        # Auto-trust new identity keys so messages can be decrypted
        exception = params.get("exception", {})
        if exception.get("type") == "UntrustedIdentityException":
            await self._trust_identity(source)
            return

        # Extract message content
        data_message = envelope.get("dataMessage", {})
        content = data_message.get("message", "")
        if not content:
            return

        # Determine chat_id: group or 1:1
        group_info = data_message.get("groupInfo", {})
        group_id = group_info.get("groupId", "")
        chat_id = f"group.{group_id}" if group_id else source

        await self._handle_message(
            sender_id=source,
            chat_id=chat_id,
            content=content,
            metadata={"timestamp": envelope.get("timestamp")},
        )

    async def _log_stderr(self) -> None:
        """Log signal-cli stderr output."""
        if not self._process or not self._process.stderr:
            return
        while self._running:
            try:
                line = await self._process.stderr.readline()
                if not line:
                    break
                text = line.decode().strip()
                if text:
                    logger.debug(f"signal-cli: {text}")
            except asyncio.CancelledError:
                break
            except Exception:
                break
