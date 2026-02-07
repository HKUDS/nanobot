"""iMessage channel implementation using the imsg CLI."""

import asyncio
import json
import shutil
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import ImsgConfig


class ImsgChannel(BaseChannel):
    """
    iMessage channel using imsg CLI for sending and receiving messages.
    
    It uses:
    - `imsg send` for outbound messages
    - `imsg watch` for listening to incoming messages (polling/stream)
    """
    
    name: str = "imsg"
    
    def __init__(self, config: ImsgConfig, bus: Any):
        super().__init__(config, bus)
        self.config = config
        self._watch_process = None
        
        # Check if imsg is installed
        if not shutil.which("imsg"):
            logger.warning("imsg CLI not found in PATH. Please install it to use iMessage channel.")
            
    async def start(self) -> None:
        """Start listening for messages via imsg watch."""
        if self._running:
            return
            
        self._running = True
        logger.info("Starting iMessage listener...")
        
        # We need to find chat_ids to watch, or watch all if possible.
        # However, `imsg watch` typically requires a specific chat-id or --all (if supported).
        # OpenClaw's skill docs say: `imsg watch --chat-id 1`
        # Let's try to watch the most recent active chats or just the configured ones.
        
        # NOTE: Since `imsg` CLI might not support a global "watch all" efficiently without a chat ID,
        # we will implement a polling loop on `imsg history` or use `imsg watch` on specific chats if needed.
        # But `imsg watch` is blocking. We'll spawn it as a subprocess.
        
        # If the user provided specific chat IDs in config, watch those.
        # Otherwise, we might need a better strategy. 
        # For now, let's assume we want to reply to anyone who messages us (if allowed).
        # Since we can't easily "watch all" with a single command without knowing IDs, 
        # and we don't want to spawn 100 processes, we will use a polling loop on `imsg chats` 
        # to find recent messages.
        
        # Actually, `imsg` might support watching the database directly?
        # Let's try a polling approach for simplicity and robustness first, 
        # as it's less likely to break if `imsg watch` behavior changes.
        
        asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop the channel."""
        self._running = False
        if self._watch_process:
            try:
                self._watch_process.terminate()
            except Exception:
                pass

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message via imsg send."""
        if not msg.content:
            return

        cmd = ["imsg", "send", "--text", msg.content]
        
        # Determine recipient
        # msg.chat_id could be a phone number (+86...) or a chat rowid (123)
        # imsg send supports --to (handle) or --chat-id (rowid)
        
        # Heuristic: if it looks like a number/email, use --to. If it looks like an int, use --chat-id.
        target = msg.chat_id
        if target.startswith("+") or "@" in target:
             cmd.extend(["--to", target])
        elif target.isdigit():
             cmd.extend(["--chat-id", target])
        else:
             # Fallback: assume handle
             cmd.extend(["--to", target])

        # Execute
        try:
            logger.debug(f"Sending iMessage to {target}: {msg.content}")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                logger.error(f"Failed to send iMessage: {stderr.decode()}")
            else:
                logger.debug(f"iMessage sent: {stdout.decode().strip()}")
                
        except Exception as e:
            logger.error(f"Error executing imsg send: {e}")

    async def _poll_loop(self) -> None:
        """Poll for new messages."""
        import time
        from datetime import datetime
        
        # Track last processed message time
        # Initialize with current time to avoid processing old history on startup
        last_check_ts = time.time()
        
        while self._running:
            try:
                # 1. Get recent chats
                proc = await asyncio.create_subprocess_exec(
                    "imsg", "chats", "--limit", "10", "--json",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await proc.communicate()
                
                if proc.returncode != 0:
                    logger.warning("Failed to fetch chats")
                    await asyncio.sleep(10)
                    continue
                
                # Parse NDJSON
                chats = []
                for line in stdout.decode().strip().splitlines():
                    if line.strip():
                        try:
                            chats.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                
                # Track the latest message timestamp seen in this batch
                max_ts_in_batch = last_check_ts
                
                for chat in chats:
                    # Check timestamp
                    last_at_str = chat.get("last_message_at")
                    if not last_at_str:
                        continue
                        
                    try:
                        # Parse ISO
                        dt = datetime.fromisoformat(last_at_str.replace('Z', '+00:00'))
                        msg_ts = dt.timestamp()
                    except ValueError:
                        continue

                    # Update max seen timestamp
                    if msg_ts > max_ts_in_batch:
                        max_ts_in_batch = msg_ts

                    # Only check if message is newer than our last global check
                    if msg_ts > last_check_ts:
                        # 2. Fetch actual message content
                        chat_id = chat.get("id")
                        if not chat_id:
                            continue
                            
                        # Fetch history to get text
                        h_proc = await asyncio.create_subprocess_exec(
                            "imsg", "history", "--chat-id", str(chat_id), "--limit", "1", "--json",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        )
                        h_stdout, _ = await h_proc.communicate()
                        
                        if h_proc.returncode != 0:
                            continue
                            
                        # Parse history NDJSON
                        msg_data = None
                        for line in h_stdout.decode().strip().splitlines():
                            if line.strip():
                                try:
                                    msg_data = json.loads(line)
                                    break 
                                except:
                                    pass
                        
                        if not msg_data:
                            continue
                            
                        if msg_data.get("is_from_me"):
                            continue
                            
                        sender = msg_data.get("sender") or chat.get("identifier")
                        text = msg_data.get("text", "")
                        
                        logger.info(f"New iMessage from {sender}: {text}")
                        
                        # Dispatch
                        await self._handle_message(
                            sender_id=sender,
                            chat_id=sender, 
                            content=text,
                            metadata={"service": chat.get("service")}
                        )

                # Update checkpoint to the latest timestamp seen
                last_check_ts = max_ts_in_batch
                
            except Exception as e:
                logger.error(f"Error in poll loop: {e}")
                
            await asyncio.sleep(2)
