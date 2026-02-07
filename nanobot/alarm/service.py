"""Alarm service - core scheduling and triggering logic."""

import asyncio
from datetime import datetime, timedelta
from typing import List, Optional

from loguru import logger

from nanobot.alarm.models import Alarm, AlarmChannel, AlarmStatus
from nanobot.alarm.storage import AlarmStorage
from nanobot.bus.queue import MessageBus


class AlarmService:
    """Service for managing and triggering alarms."""
    
    def __init__(self, storage: AlarmStorage, bus: Optional[MessageBus] = None):
        """Initialize alarm service.
        
        Args:
            storage: Alarm storage instance
            bus: Message bus for notifications
        """
        self.storage = storage
        self.bus = bus
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._check_interval = 5  # seconds between checks
    
    async def create_alarm(
        self,
        user_id: str,
        message: str,
        delay_seconds: int,
        channel: str = AlarmChannel.TELEGRAM,
    ) -> Alarm:
        """Create a new alarm.
        
        Args:
            user_id: User/chat identifier
            message: Alarm message
            delay_seconds: Seconds until trigger
            channel: Notification channel
        
        Returns:
            Created alarm
        """
        trigger_at = datetime.now() + timedelta(seconds=delay_seconds)
        
        alarm = Alarm(
            user_id=user_id,
            channel=channel,
            message=message,
            trigger_at=trigger_at,
        )
        
        self.storage.save_alarm(alarm)
        logger.info(f"Created alarm {alarm.id} for {user_id} in {delay_seconds}s")
        
        return alarm
    
    async def create_alarm_at(
        self,
        user_id: str,
        message: str,
        trigger_at: datetime,
        channel: str = AlarmChannel.TELEGRAM,
    ) -> Alarm:
        """Create alarm for specific time.
        
        Args:
            user_id: User/chat identifier
            message: Alarm message
            trigger_at: Exact trigger datetime
            channel: Notification channel
        
        Returns:
            Created alarm
        """
        alarm = Alarm(
            user_id=user_id,
            channel=channel,
            message=message,
            trigger_at=trigger_at,
        )
        
        self.storage.save_alarm(alarm)
        logger.info(f"Created alarm {alarm.id} for {user_id} at {trigger_at}")
        
        return alarm
    
    def list_alarms(
        self,
        user_id: Optional[str] = None,
        status: Optional[AlarmStatus] = None,
    ) -> List[Alarm]:
        """List alarms with optional filtering.
        
        Args:
            user_id: Filter by user (optional)
            status: Filter by status (optional)
        
        Returns:
            List of matching alarms
        """
        alarms = self.storage.load_all_alarms()
        
        if user_id:
            alarms = [a for a in alarms if a.user_id == user_id]
        
        if status:
            alarms = [a for a in alarms if a.status == status]
        
        # Sort by trigger time
        alarms.sort(key=lambda a: a.trigger_at)
        
        return alarms
    
    def get_alarm(self, alarm_id: str) -> Optional[Alarm]:
        """Get alarm by ID."""
        return self.storage.get_alarm_by_id(alarm_id)
    
    def cancel_alarm(self, alarm_id: str) -> bool:
        """Cancel a pending alarm.
        
        Args:
            alarm_id: Alarm ID to cancel
        
        Returns:
            True if cancelled, False if not found
        """
        alarm = self.get_alarm(alarm_id)
        if not alarm:
            return False
        
        if alarm.status != AlarmStatus.PENDING:
            logger.warning(f"Cannot cancel alarm {alarm_id}: status is {alarm.status.value}")
            return False
        
        success = self.storage.update_alarm_status(alarm_id, AlarmStatus.CANCELLED)
        if success:
            logger.info(f"Cancelled alarm {alarm_id}")
        
        return success
    
    async def trigger_alarm(self, alarm: Alarm) -> None:
        """Trigger an alarm notification.
        
        Args:
            alarm: Alarm to trigger
        """
        logger.info(f"Triggering alarm {alarm.id}: {alarm.message}")
        
        # Mark as triggered
        self.storage.update_alarm_status(alarm.id, AlarmStatus.TRIGGERED)
        
        # Send notification
        await self._send_notification(alarm)
    
    async def _send_notification(self, alarm: Alarm) -> None:
        """Send alarm notification through appropriate channel."""
        notification = f"⏰ <b>ALARME!</b>\n\n{alarm.message}"
        
        if alarm.channel == AlarmChannel.CONSOLE:
            # Console notification
            print(f"\n{'='*50}")
            print(notification.replace("<b>", "").replace("</b>", ""))
            print(f"{'='*50}\n")
            
        elif alarm.channel == AlarmChannel.TELEGRAM and self.bus:
            # Send via Telegram channel through message bus
            from nanobot.bus.events import OutboundMessage
            
            msg = OutboundMessage(
                content=notification,
                chat_id=alarm.user_id,
                channel="telegram",
            )
            await self.bus.publish(msg)
            
        elif alarm.channel == AlarmChannel.ALL:
            # Try all channels
            await self._send_notification(
                Alarm(
                    id=alarm.id,
                    user_id=alarm.user_id,
                    channel=AlarmChannel.CONSOLE,
                    message=alarm.message,
                    trigger_at=alarm.trigger_at,
                )
            )
            if self.bus:
                await self._send_notification(
                    Alarm(
                        id=alarm.id,
                        user_id=alarm.user_id,
                        channel=AlarmChannel.TELEGRAM,
                        message=alarm.message,
                        trigger_at=alarm.trigger_at,
                    )
                )
        
        logger.debug(f"Notification sent for alarm {alarm.id}")
    
    async def start_scheduler(self) -> None:
        """Start the alarm scheduler loop."""
        self._running = True
        logger.info("Alarm scheduler started")
        
        while self._running:
            try:
                await self._check_and_trigger()
                await asyncio.sleep(self._check_interval)
            except Exception as e:
                logger.error(f"Error in alarm scheduler: {e}")
                await asyncio.sleep(self._check_interval)
        
        logger.info("Alarm scheduler stopped")
    
    async def _check_and_trigger(self) -> None:
        """Check for due alarms and trigger them."""
        pending = self.storage.get_pending_alarms()
        now = datetime.now()
        
        for alarm in pending:
            if alarm.trigger_at <= now:
                await self.trigger_alarm(alarm)
    
    def stop_scheduler(self) -> None:
        """Stop the scheduler loop."""
        self._running = False
        logger.info("Alarm scheduler stopping...")
    
    async def cleanup(self, max_age_days: int = 7) -> int:
        """Cleanup old triggered alarms.
        
        Args:
            max_age_days: Age threshold for cleanup
        
        Returns:
            Number of alarms removed
        """
        return self.storage.cleanup_old_triggered(max_age_days)


def parse_time_string(time_str: str) -> int:
    """Parse time string like '2m', '1h30m', '30s' into seconds.
    
    Args:
        time_str: Time string (e.g., "2m", "1h30m", "30s")
    
    Returns:
        Total seconds
    
    Raises:
        ValueError: If format is invalid
    """
    import re
    
    pattern = r'^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$'
    match = re.match(pattern, time_str.lower())
    
    if not match:
        raise ValueError(f"Invalid time format: {time_str}. Use format like '2m', '1h30m', '30s'")
    
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    
    total = hours * 3600 + minutes * 60 + seconds
    
    if total == 0:
        raise ValueError("Time must be greater than 0")
    
    return total
