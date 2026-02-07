"""
nanobot - A lightweight AI agent framework
"""

import os
import sys

__version__ = "0.1.0"
__logo__ = "🐈"

# 配置 loguru 日志级别
from loguru import logger

level = os.environ.get("LOG_LEVEL", " INFO").upper()

# 使用默认配置，不添加自定义 handler
# 导出 logger 供其他模块使用

# 导出配置好的 logger供其他模块使用
