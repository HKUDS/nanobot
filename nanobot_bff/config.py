"""Configuration for Nanobot BFF service."""

import os
from pathlib import Path

# Base paths
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_PATH = DATA_DIR / "nanobot_bff.db"

# Nanobot configuration
NANOBOT_WORKSPACE = os.environ.get("NANOBOT_WORKSPACE", str(PROJECT_ROOT / "workspace"))
DEFAULT_MODEL = os.environ.get("NANOBOT_MODEL", "deepseek-chat")
MAX_ITERATIONS = 40

# API Keys (loaded from environment)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")

# Server configuration
HOST = os.environ.get("BFF_HOST", "0.0.0.0")
PORT = int(os.environ.get("BFF_PORT", "8000"))
