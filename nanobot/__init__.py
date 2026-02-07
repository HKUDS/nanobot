"""
nanobot - A lightweight AI agent framework
"""

import os
import sys

__version__ = "0.1.0"
__logo__ = "🐈"

# 配置 loguru 日志级别（在模块导入时立即配置）
from loguru import _logger

level = os.environ.get("LOG_LEVEL", "INFO").upper()

_logger.remove()
_logger.add(
    sys.stderr,
    format="<level>{time:YYYY-MM-DD HH:mm:ss} | {name}:{function}:{line} | {message}",
    level=level,
    colorize=True,
    backtrace=True,
    diagnose=True,
)

# 导出配置好的 logger
logger = _logger
