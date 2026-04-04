"""Configuration for milestone2 containerized architecture."""

import os

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-b192d1bf26f740adace7d5f628656921")
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "sk-91fe1c9c529b46bb88dc200a2e97b2b6")

DOCKER_IMAGE = os.environ.get("DOCKER_IMAGE", "nanobot-agent:latest")
MEMORY_LIMIT = os.environ.get("MEMORY_LIMIT", "512m")
CPU_LIMIT = float(os.environ.get("CPU_LIMIT", "0.5"))

MAX_ACTIVE_CONTAINERS = int(os.environ.get("MAX_ACTIVE_CONTAINERS", "20"))
