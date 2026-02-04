"""Storage for alarms - JSONL persistence."""

import json
from pathlib import Path
from typing import List, Optional

from loguru import logger

from nanobot.alarm.models import Alarm, AlarmStatus
from nanobot.utils.helpers import ensure_dir


class AlarmStorage:
    """Persistent storage for alarms using JSONL format."""
    
    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize storage with data directory."""
        if data_dir is None:
            data_dir = Path.home() / ".nanobot" / "alarms"
        
        self.data_dir = ensure_dir(data_dir)
        self.alarms_file = self.data_dir / "alarms.jsonl"
    
    def save_alarm(self, alarm: Alarm) -> None:
        """Save a new alarm to storage (append)."""
        try:
            with open(self.alarms_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(alarm.to_dict(), ensure_ascii=False) + "\n")
            logger.debug(f"Alarm {alarm.id} saved")
        except Exception as e:
            logger.error(f"Failed to save alarm {alarm.id}: {e}")
            raise
    
    def load_all_alarms(self) -> List[Alarm]:
        """Load all alarms from storage."""
        alarms = []
        
        if not self.alarms_file.exists():
            return alarms
        
        try:
            with open(self.alarms_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        alarms.append(Alarm.from_dict(data))
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.warning(f"Skipping invalid alarm entry: {e}")
                        continue
        except Exception as e:
            logger.error(f"Failed to load alarms: {e}")
        
        return alarms
    
    def get_pending_alarms(self) -> List[Alarm]:
        """Get all pending alarms."""
        all_alarms = self.load_all_alarms()
        return [a for a in all_alarms if a.status == AlarmStatus.PENDING]
    
    def get_alarm_by_id(self, alarm_id: str) -> Optional[Alarm]:
        """Find alarm by ID."""
        for alarm in self.load_all_alarms():
            if alarm.id == alarm_id:
                return alarm
        return None
    
    def update_alarm_status(self, alarm_id: str, new_status: AlarmStatus) -> bool:
        """Update status of an alarm (rewrite entire file)."""
        alarms = self.load_all_alarms()
        found = False
        
        for alarm in alarms:
            if alarm.id == alarm_id:
                alarm.status = new_status
                found = True
                logger.debug(f"Alarm {alarm_id} status changed to {new_status.value}")
                break
        
        if found:
            self._rewrite_all(alarms)
        
        return found
    
    def delete_alarm(self, alarm_id: str) -> bool:
        """Delete an alarm by ID."""
        alarms = self.load_all_alarms()
        original_count = len(alarms)
        alarms = [a for a in alarms if a.id != alarm_id]
        
        if len(alarms) < original_count:
            self._rewrite_all(alarms)
            logger.debug(f"Alarm {alarm_id} deleted")
            return True
        
        return False
    
    def _rewrite_all(self, alarms: List[Alarm]) -> None:
        """Rewrite all alarms to file."""
        try:
            with open(self.alarms_file, "w", encoding="utf-8") as f:
                for alarm in alarms:
                    f.write(json.dumps(alarm.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to rewrite alarms file: {e}")
            raise
    
    def cleanup_old_triggered(self, max_age_days: int = 7) -> int:
        """Remove old triggered alarms. Returns count removed."""
        from datetime import datetime, timedelta
        
        alarms = self.load_all_alarms()
        cutoff = datetime.now() - timedelta(days=max_age_days)
        
        filtered = [
            a for a in alarms 
            if not (a.status == AlarmStatus.TRIGGERED and a.trigger_at < cutoff)
        ]
        
        removed = len(alarms) - len(filtered)
        if removed > 0:
            self._rewrite_all(filtered)
            logger.info(f"Cleaned up {removed} old triggered alarms")
        
        return removed
