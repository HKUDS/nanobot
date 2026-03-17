"""
nanobot - A lightweight AI agent framework
"""

import os
from pathlib import Path
from loguru import logger

__version__ = "0.1.4.post5"
__logo__ = "🐈"

# Create logs directory
logs_dir = Path(__file__).parent.parent / "logs"
logs_dir.mkdir(exist_ok=True)

# Configure loguru to include trace_id in log format
logger.remove()
logger.add(
    str(logs_dir / "nanobot.log"),
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {extra[trace_id]: <36} | {name}:{function}:{line} - {message}",
    level="INFO",
    rotation="100MB",
    compression="zip"
)
logger.add(
    "stdout",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {extra[trace_id]: <36} | {name}:{function}:{line} - {message}",
    level="INFO"
)

