"""Token usage logger - writes usage stats to a dedicated file."""

import os
from pathlib import Path
from datetime import datetime
from loguru import logger


def get_usage_log_path() -> Path:
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


def configure_usage_logger() -> None:
    """Configure a dedicated logger for token usage."""
    log_path = get_usage_log_path()
    
    # 移除可能存在的相同文件handler
    try:
        # 查找并移除指向相同文件的handler
        for handler_id, handler in list(logger._core.handlers.items()):
            if hasattr(handler._sink, 'name') and str(handler._sink.name) == str(log_path):
                logger.remove(handler_id)
    except:
        pass
    
    logger.add(
        log_path,
        rotation="10 MB",
        retention="30 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
        level="INFO",
        enqueue=True,
    )


def log_usage(usage: dict[str, int], session_key: str | None = None) -> None:
    """Log token usage to the dedicated file."""
    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    total = usage.get("total_tokens", prompt + completion)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session_info = f"[{session_key}]" if session_key else ""
    logger.info(
        "{session} prompt={prompt}, completion={completion}, total={total}",
        session=session_info,
        prompt=prompt,
        completion=completion,
        total=total,
    )
