"""
nanobot - A lightweight AI agent framework
"""

from importlib.metadata import version as _pkg_version

__version__ = _pkg_version("nanobot-ai")
__logo__ = "🐈"

from nanobot.nanobot import Nanobot, RunResult

__all__ = ["Nanobot", "RunResult"]
