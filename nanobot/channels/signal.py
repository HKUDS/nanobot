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
        self._pending_rpc: dict[int, asyncio.Future] = {}  # id -> Future for RPC responses
        # UUID → phone number cache so allowFrom works with phone numbers only
        self._uuid_to_number: dict[str, str] = {}

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

        # Resolve allowFrom phone numbers → UUIDs in background
        asyncio.create_task(self._resolve_allow_list())

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

    async def _rpc_call(self, method: str, params: dict) -> dict | None:
        """Send a JSON-RPC request and return the result (with timeout)."""
        self._rpc_id += 1
        rpc_id = self._rpc_id
        request = {"jsonrpc": "2.0", "method": method, "id": rpc_id, "params": params}
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_rpc[rpc_id] = future
        try:
            line = json.dumps(request) + "\n"
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()
            return await asyncio.wait_for(future, timeout=10)
        except asyncio.TimeoutError:
            logger.warning(f"RPC call {method} (id={rpc_id}) timed out")
            return None
        except Exception as e:
            logger.error(f"RPC call {method} failed: {e}")
            return None
        finally:
            self._pending_rpc.pop(rpc_id, None)

    async def _handle_jsonrpc(self, data: dict) -> None:
        """Handle a JSON-RPC message from signal-cli."""
        method = data.get("method")

        if method == "receive":
            await self._on_receive(data.get("params", {}))
        elif method:
            logger.debug(f"signal-cli unhandled method: {method}")
        elif "id" in data:
            rpc_id = data["id"]
            future = self._pending_rpc.pop(rpc_id, None)
            if future and not future.done():
                if "error" in data:
                    logger.error(f"signal-cli RPC error: {data['error']}")
                    future.set_result(None)
                else:
                    future.set_result(data.get("result"))
            else:
                if "error" in data:
                    logger.error(f"signal-cli RPC error: {data['error']}")
                else:
                    logger.debug(f"signal-cli RPC response id={rpc_id}")

    async def _resolve_allow_list(self) -> None:
        """Build UUID→phone cache from contacts and getUserStatus.

        Linked devices often don't have sourceNumber on incoming messages,
        so we need this cache to match allowFrom phone numbers against UUIDs.
        """
        phone_numbers = [n for n in self.config.allow_from if n.startswith("+")]
        if not phone_numbers:
            return

        # First try listContacts — returns all synced contacts with number + uuid
        contacts = await self._rpc_call("listContacts", {})
        if contacts and isinstance(contacts, list):
            for entry in contacts:
                uuid = entry.get("uuid") or ""
                number = entry.get("number") or ""
                if uuid and number:
                    self._uuid_to_number[uuid] = number

        # Also try getUserStatus for any numbers not yet resolved
        unresolved = [n for n in phone_numbers if n not in self._uuid_to_number.values()]
        if unresolved:
            result = await self._rpc_call("getUserStatus", {"recipient": unresolved})
            if result:
                for entry in result if isinstance(result, list) else [result]:
                    uuid = entry.get("uuid")
                    number = entry.get("number", "")
                    if uuid and number:
                        self._uuid_to_number[uuid] = number

        resolved = sum(1 for n in phone_numbers if n in self._uuid_to_number.values())
        if resolved:
            logger.info(f"Resolved {resolved}/{len(phone_numbers)} allowFrom numbers to UUIDs")
        if resolved < len(phone_numbers):
            logger.warning(
                f"{len(phone_numbers) - resolved} allowFrom number(s) could not be resolved. "
                "Linked devices may need a contact sync. "
                "You can also add UUIDs directly to allowFrom."
            )

    async def _trust_identity(self, source: str) -> None:
        """Auto-trust a sender's new identity key via JSON-RPC."""
        result = await self._rpc_call("trust", {"recipient": source, "trustAllKnownKeys": True})
        if result is not None:
            logger.info(f"Auto-trusted new identity for {source}")
        else:
            logger.warning(f"Trust call for {source} returned no result (may still have worked)")

    async def _on_receive(self, params: dict) -> None:
        """Handle an incoming Signal message."""
        envelope = params.get("envelope", {})
        # sourceNumber can be null (e.g. UntrustedIdentityException), fall back to UUID
        source = envelope.get("sourceNumber") or envelope.get("sourceUuid", "")

        # Auto-trust MUST be checked before the empty-source guard,
        # because untrusted envelopes often have sourceNumber=null
        exception = params.get("exception", {})
        if exception.get("type") == "UntrustedIdentityException":
            if source:
                await self._trust_identity(source)
            else:
                logger.warning("UntrustedIdentityException with no source identifier")
            return

        if not source:
            return

        # Extract message content
        data_message = envelope.get("dataMessage", {})
        content = data_message.get("message", "")
        if not content:
            return

        # Resolve source identity: prefer phone number for allowFrom matching.
        # signal-cli linked devices often have sourceNumber=null, so look up UUID cache.
        source_number = envelope.get("sourceNumber") or ""
        source_uuid = envelope.get("sourceUuid") or ""
        if not source_number and source_uuid:
            source_number = self._uuid_to_number.get(source_uuid, "")
        # Cache any new UUID→number mapping we discover
        if source_number and source_uuid:
            self._uuid_to_number[source_uuid] = source_number

        # Build sender_id with both number and UUID so allowFrom can match either.
        # BaseChannel.is_allowed splits on "|" and checks each part.
        parts = [p for p in (source_number, source_uuid) if p]
        sender_id = "|".join(parts) if parts else source

        # Determine chat_id: group or 1:1 (prefer phone number for outbound sends)
        group_info = data_message.get("groupInfo", {})
        group_id = group_info.get("groupId", "")
        chat_id = f"group.{group_id}" if group_id else (source_number or source_uuid)

        await self._handle_message(
            sender_id=sender_id,
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
