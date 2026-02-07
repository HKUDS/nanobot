"""
nanobot - A lightweight AI agent framework
"""

import os
import sys

__version__ = "0.1.0"
__logo__ = "🐈"

# 配置 loguru 日志级别
from loguru import _logger

level = os.environ.get("LOG_LEVEL", "INFO").upper()

# 配置 loguru（使用默认配置，不再添加自定义 handler）
logger = _logger

# 导出配置好的 logger供其他模块使用
