"""Pluggable execution backends for the ``computer_use`` tool.

Backends are plain classes (NOT ``Tool`` subclasses), so ``ToolLoader`` never
mistakes them for tools. Importing this package must stay cheap: the heavy,
optional dependencies (pyautogui / Pillow / playwright) are imported lazily
inside the concrete backend modules and never at import time here.
"""

from nanobot.agent.tools.computer_use_backends.base import ComputerBackend

__all__ = ["ComputerBackend"]
