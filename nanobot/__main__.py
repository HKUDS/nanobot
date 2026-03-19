"""
Entry point for running nanobot as a module: python -m nanobot
"""

from __future__ import annotations

from nanobot.cli.commands import app

if __name__ == "__main__":
    app()
