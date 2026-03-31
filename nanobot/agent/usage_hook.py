"""Usage logging hook - records token usage after each LLM call."""

import os
from pathlib import Path
from loguru import logger


class UsageLoggingHook:
    """Hook that logs token usage to a dedicated file."""

    def __init__(self):
        self._log_path = self._get_log_path()
        self._configured = False

    def _get_log_path(self) -> Path:
        """Get the token usage log file path.
        
        Supports Docker isolation via NANOBOT_WORKSPACE environment variable.
        """
        # 支持 Docker 容器隔离：使用环境变量指定的 workspace
        workspace_env = os.environ.get("NANOBOT_WORKSPACE")
        if workspace_env:
            workspace = Path(workspace_env)
        else:
            workspace = Path(os.path.expanduser("~/.nanobot/workspace"))
        
        personal_dir = workspace / "personal"
        personal_dir.mkdir(parents=True, exist_ok=True)
        return personal_dir / "token_usage.txt"

    def _ensure_configured(self) -> None:
        if self._configured:
            return
        try:
            for handler_id, handler in list(logger._core.handlers.items()):
                if hasattr(handler._sink, 'name') and str(handler._sink.name) == str(self._log_path):
                    logger.remove(handler_id)
        except Exception:
            pass

        logger.add(
            self._log_path,
            rotation="10 MB",
            retention="30 days",
            format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
            level="INFO",
        )
        self._configured = True

    async def after_iteration(self, context) -> None:
        """Called after each iteration. Log usage if available."""
        self._ensure_configured()
        if not context.usage:
            return
        usage = context.usage
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        total = prompt + completion
        session_info = f"[{context.messages[0].get('session_key', 'unknown') if context.messages else 'unknown'}]"
        logger.info(
            "{session} prompt={prompt}, completion={completion}, total={total}",
            session=session_info,
            prompt=prompt,
            completion=completion,
            total=total,
        )
