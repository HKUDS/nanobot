"""Simple progress indicator for Agent operations.

Simplified version: sends a message every 30 seconds showing current stage.
"""

import asyncio
import time
from typing import Optional, Callable, Awaitable, Any

from loguru import logger


class ProgressReporter:
    """
    Simple progress reporter for Agent operations.
    
    Sends a text message every 2 minutes showing the current stage.
    No cards, no animations - just simple periodic updates.
    """
    
    def __init__(
        self,
        channel: str,
        chat_id: str,
        sender: Callable[[str], Awaitable[Any]],
        bot_name: str = "Agent",
        update_interval: float = 120.0,  # Send update every 2 minutes
    ):
        """
        Initialize simple progress reporter.
        
        Args:
            channel: Channel name
            chat_id: Chat ID to send updates to
            sender: Async function to send text messages
            bot_name: Name to display
            update_interval: Seconds between updates (default 30s)
        """
        self.channel = channel
        self.chat_id = chat_id
        self._send = sender
        self.bot_name = bot_name
        self.update_interval = update_interval
        
        self._active: bool = False
        self._update_task: Optional[asyncio.Task] = None
        self._current_phase: str = ""
        self._start_time: float = 0
        
    def start(self, phase: str) -> None:
        """Start progress tracking with initial phase."""
        self._active = True
        self._current_phase = phase
        self._start_time = time.time()
        
        # Start background task that sends updates every 30 seconds
        self._update_task = asyncio.create_task(self._update_loop())
        logger.debug(f"[Progress] Started tracking phase: {phase}")
    
    def set_phase(self, phase: str) -> None:
        """Update the current phase."""
        self._current_phase = phase
        logger.debug(f"[Progress] Phase updated to: {phase}")
    
    def update(self, phase: str, percent: int = 0, detail: str = "") -> bool:
        """
        Update progress (compatibility method for _run_agent_loop).
        Just updates the phase, ignores percent and detail.
        """
        self.set_phase(phase)
        return True
    
    async def _update_loop(self) -> None:
        """Background loop that sends update messages every 2 minutes."""
        await asyncio.sleep(self.update_interval)  # Wait first interval before sending
        
        while self._active:
            try:
                elapsed = time.time() - self._start_time
                minutes = int(elapsed // 60)
                seconds = int(elapsed % 60)
                time_str = f"{minutes}分{seconds}秒" if minutes > 0 else f"{seconds}秒"
                
                message = f"⏳ {self.bot_name}还在处理中...\n当前阶段：{self._current_phase}\n已用时：{time_str}"
                await self._send(message)
                logger.debug(f"[Progress] Sent update: {self._current_phase}, elapsed: {time_str}")
                
            except Exception as e:
                logger.warning(f"[Progress] Failed to send update: {e}")
            
            await asyncio.sleep(self.update_interval)
    
    def stop(self) -> None:
        """Stop progress tracking and cancel the update task."""
        self._active = False
        if self._update_task and not self._update_task.done():
            self._update_task.cancel()
        logger.debug("[Progress] Stopped tracking")


class NullProgressReporter:
    """No-op progress reporter for when progress is disabled."""
    
    def __init__(self):
        pass
        
    def start(self, phase: str) -> None:
        pass
    
    def set_phase(self, phase: str) -> None:
        pass
    
    def update(self, phase: str, percent: int = 0, detail: str = "") -> bool:
        """No-op update for compatibility."""
        return True
    
    def stop(self) -> None:
        pass
