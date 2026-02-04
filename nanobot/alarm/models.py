"""Models for alarm system."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid


class AlarmStatus(str, Enum):
    """Status of an alarm."""
    PENDING = "pending"
    TRIGGERED = "triggered"
    CANCELLED = "cancelled"


class AlarmChannel(str, Enum):
    """Channel for alarm notification."""
    TELEGRAM = "telegram"
    CONSOLE = "console"
    ALL = "all"


@dataclass
class Alarm:
    """Represents a scheduled alarm."""
    
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_id: str = ""  # chat_id or user identifier
    channel: str = AlarmChannel.TELEGRAM  # notification channel
    message: str = ""  # alarm message
    trigger_at: datetime = field(default_factory=datetime.now)
    created_at: datetime = field(default_factory=datetime.now)
    status: AlarmStatus = AlarmStatus.PENDING
    
    def to_dict(self) -> dict:
        """Convert alarm to dictionary for serialization."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "channel": self.channel,
            "message": self.message,
            "trigger_at": self.trigger_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "status": self.status.value,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Alarm":
        """Create alarm from dictionary."""
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            channel=data["channel"],
            message=data["message"],
            trigger_at=datetime.fromisoformat(data["trigger_at"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            status=AlarmStatus(data["status"]),
        )
    
    def is_due(self) -> bool:
        """Check if alarm should trigger now."""
        return self.status == AlarmStatus.PENDING and datetime.now() >= self.trigger_at
    
    def __str__(self) -> str:
        """String representation of alarm."""
        time_str = self.trigger_at.strftime("%H:%M:%S")
        return f"[{self.id}] {self.message} @ {time_str} ({self.status.value})"
