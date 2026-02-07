"""Tool execution logger for session-paired audit trails."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger


class ToolLogger:
    """
    Logs tool executions to session-specific JSONL files.
    
    Each session gets its own log file at: <workspace>/logs/<session_key>.jsonl
    """
    
    MAX_RESULT_LENGTH = 2000
    
    def __init__(self, workspace: Path):
        self.logs_dir = workspace / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
    
    def _sanitize_session_key(self, session_key: str) -> str:
        """Convert session key to safe filename."""
        return re.sub(r'[<>:"/\\|?*]', '_', session_key)
    
    def _get_log_path(self, session_key: str) -> Path:
        """Get log file path for session."""
        return self.logs_dir / f"{self._sanitize_session_key(session_key)}.jsonl"
    
    async def log_tool_call(
        self,
        session_key: str,
        tool_name: str,
        params: dict[str, Any],
        result: str,
        duration_ms: float,
    ) -> None:
        """Log a tool execution to the session's log file."""
        log_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": tool_name,
            "params": params,
            "result": self._truncate(result),
            "ms": round(duration_ms, 2),
        }
        
        try:
            with open(self._get_log_path(session_key), "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write tool log: {e}")
    
    def _truncate(self, text: str) -> str:
        """Truncate long results to keep log files manageable."""
        if len(text) > self.MAX_RESULT_LENGTH:
            return text[:self.MAX_RESULT_LENGTH] + f"...[{len(text)} chars]"
        return text
