"""Alarm tool for creating reminders and timers."""

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import BaseTool
from nanobot.alarm import AlarmService, AlarmStorage, AlarmChannel, parse_time_string


class AlarmTool(BaseTool):
    """
    Tool for creating alarms, reminders and timers.
    
    This tool allows the AI to set alarms for users that will trigger
    notifications at specified times.
    
    Examples:
    - "Set an alarm for 2 minutes" -> delay_seconds=120
    - "Remind me in 30 minutes" -> delay_seconds=1800
    - "Alarm at 3 PM" -> specific time calculation
    """
    
    @property
    def name(self) -> str:
        return "alarm"
    
    @property
    def description(self) -> str:
        return "Create alarms, reminders and timers. Set notifications for future times."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The alarm message or reminder content"
                },
                "delay_seconds": {
                    "type": "integer",
                    "description": "Seconds until alarm triggers (e.g., 120 for 2 minutes)"
                },
                "time_string": {
                    "type": "string",
                    "description": "Human readable time like '2m', '30s', '1h30m', '5 minutes'"
                },
                "channel": {
                    "type": "string",
                    "enum": ["telegram", "console", "all"],
                    "description": "Where to send the notification",
                    "default": "telegram"
                }
            },
            "required": ["message"],
            "oneOf": [
                {"required": ["delay_seconds"]},
                {"required": ["time_string"]}
            ]
        }
    
    async def execute(
        self,
        message: str,
        delay_seconds: int = 0,
        time_string: str = "",
        channel: str = "telegram",
        **kwargs
    ) -> str:
        """
        Create an alarm.
        
        Args:
            message: The alarm message
            delay_seconds: Seconds until trigger
            time_string: Alternative time format (e.g., '2m', '1h')
            channel: Notification channel
        
        Returns:
            Confirmation message with alarm details
        """
        try:
            # Parse time_string if provided
            if time_string and not delay_seconds:
                # Normalize common phrases
                normalized = self._normalize_time_string(time_string)
                try:
                    delay_seconds = parse_time_string(normalized)
                except ValueError as e:
                    return f"Error: Could not parse time '{time_string}'. Use format like '2m', '30s', '1h'."
            
            if delay_seconds <= 0:
                return "Error: Time must be greater than 0 seconds."
            
            # Get user context from kwargs if available
            user_id = kwargs.get("user_id", "unknown")
            chat_id = kwargs.get("chat_id", user_id)
            
            # Create alarm service
            storage = AlarmStorage()
            service = AlarmService(storage)
            
            # Create the alarm
            alarm = await service.create_alarm(
                user_id=str(chat_id),
                message=message,
                delay_seconds=delay_seconds,
                channel=channel
            )
            
            # Format time for display
            trigger_at = alarm.trigger_at
            time_display = trigger_at.strftime("%H:%M:%S")
            
            # Calculate human-readable duration
            duration_str = self._format_duration(delay_seconds)
            
            logger.info(f"Alarm created via tool: {alarm.id} for user {chat_id}")
            
            return (
                f"✅ Alarm set!\n"
                f"📝 Message: {message}\n"
                f"⏰ Triggers at: {time_display} (in {duration_str})\n"
                f"📢 Channel: {channel}\n"
                f"🆔 Alarm ID: {alarm.id}"
            )
            
        except Exception as e:
            logger.error(f"Error creating alarm: {e}")
            return f"Error creating alarm: {str(e)}"
    
    def _normalize_time_string(self, time_str: str) -> str:
        """Normalize various time phrases to parseable format."""
        time_str = time_str.lower().strip()
        
        # Common mappings
        patterns = [
            # "X minutes" -> Xm
            (r'(\d+)\s*min(?:uto)?s?', r'\1m'),
            # "X hours" -> Xh  
            (r'(\d+)\s*h(?:our)?s?', r'\1h'),
            # "X seconds" -> Xs
            (r'(\d+)\s*s(?:ec)?(?:ond)?s?', r'\1s'),
            # "X min" -> Xm
            (r'(\d+)\s*min', r'\1m'),
            # "X hr" -> Xh
            (r'(\d+)\s*hr', r'\1h'),
        ]
        
        for pattern, replacement in patterns:
            time_str = re.sub(pattern, replacement, time_str)
        
        # Remove extra spaces
        time_str = time_str.replace(' ', '')
        
        return time_str
    
    def _format_duration(self, seconds: int) -> str:
        """Format seconds into human-readable duration."""
        if seconds < 60:
            return f"{seconds} seconds"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            if secs == 0:
                return f"{minutes} minute{'s' if minutes > 1 else ''}"
            return f"{minutes}m {secs}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            if minutes == 0:
                return f"{hours} hour{'s' if hours > 1 else ''}"
            return f"{hours}h {minutes}m"


class ListAlarmsTool(BaseTool):
    """Tool for listing pending alarms."""
    
    @property
    def name(self) -> str:
        return "list_alarms"
    
    @property
    def description(self) -> str:
        return "List all pending alarms and reminders."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": []
        }
    
    async def execute(self, **kwargs) -> str:
        """List pending alarms."""
        try:
            user_id = kwargs.get("chat_id", "unknown")
            
            storage = AlarmStorage()
            service = AlarmService(storage)
            
            from nanobot.alarm.models import AlarmStatus
            alarms = service.list_alarms(user_id=str(user_id), status=AlarmStatus.PENDING)
            
            if not alarms:
                return "No pending alarms."
            
            lines = [f"⏰ You have {len(alarms)} pending alarm(s):\n"]
            for alarm in alarms:
                time_str = alarm.trigger_at.strftime("%Y-%m-%d %H:%M")
                lines.append(f"• [{alarm.id}] {alarm.message} - {time_str}")
            
            return "\n".join(lines)
            
        except Exception as e:
            logger.error(f"Error listing alarms: {e}")
            return f"Error listing alarms: {str(e)}"


class CancelAlarmTool(BaseTool):
    """Tool for cancelling alarms."""
    
    @property
    def name(self) -> str:
        return "cancel_alarm"
    
    @property
    def description(self) -> str:
        return "Cancel a pending alarm by its ID."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "alarm_id": {
                    "type": "string",
                    "description": "The alarm ID to cancel"
                }
            },
            "required": ["alarm_id"]
        }
    
    async def execute(self, alarm_id: str, **kwargs) -> str:
        """Cancel an alarm."""
        try:
            storage = AlarmStorage()
            service = AlarmService(storage)
            
            success = service.cancel_alarm(alarm_id)
            
            if success:
                return f"✅ Alarm {alarm_id} cancelled successfully."
            else:
                return f"❌ Could not cancel alarm {alarm_id}. It may not exist or already triggered."
                
        except Exception as e:
            logger.error(f"Error cancelling alarm: {e}")
            return f"Error cancelling alarm: {str(e)}"
