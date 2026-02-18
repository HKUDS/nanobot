"""
nanobot - A lightweight AI agent framework
"""

from __future__ import annotations
from pathlib import Path


def _get_version() -> str:
    """Read version from pyproject.toml."""
    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
    if pyproject_path.exists():
        try:
            import tomllib  # Python 3.11+
        except ImportError:
            import tomli as tomllib  # Python <3.11 fallback
        data = tomllib.loads(pyproject_path.read_text())
        return data["project"]["version"]
    return "0.0.0-unknown"


__version__ = _get_version()
__logo__ = "🐈"
