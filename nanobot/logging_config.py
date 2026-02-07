"""Loguru 日志配置模块."""

import os
import sys
from loguru import logger


def setup_logging(level: str | None = None) -> None:
    """配置 loguru 日志级别。"""
    if level is None:
        # 从环境变量读取日志级别
        level = os.environ.get("LOG_LEVEL", "INFO").upper()

    # 配置 loguru
    logger.remove()  # 移除默认的 handler
    logger.add(
        sys.stderr,
        format="<level>{time:YYYY-MM-DD HH:mm:ss} | {name}:{function}:{line} | {message}",
        level=level,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )


# 应用配置
if __name__ == "__main__":
    setup_logging()
