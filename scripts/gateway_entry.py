"""PyInstaller entry point for nanobot gateway sidecar."""
import sys

sys.argv = ["nanobot", "gateway"] + sys.argv[1:]

from nanobot.cli.commands import app

app()
