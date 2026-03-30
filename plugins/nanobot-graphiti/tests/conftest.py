"""Shared fixtures for nanobot-graphiti tests."""

import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the worktree's nanobot package takes priority over the installed one.
# The editable install adds /home/empty/PaiBot to sys.path via a .pth file, but
# the site-packages nanobot/ namespace package causes the wrong version to be
# found when MemoryBackend hasn't been added to main yet. We insert the
# worktree root at position 0 so the worktree's nanobot/__init__.py wins.
# ---------------------------------------------------------------------------
_WORKTREE_ROOT = str(Path(__file__).resolve().parents[4])  # .../graphiti-memory
if _WORKTREE_ROOT not in sys.path:
    sys.path.insert(0, _WORKTREE_ROOT)
from enum import Enum
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub out graphiti_core.nodes so that `from graphiti_core.nodes import
# EpisodeType` works in tests without installing the real graphiti_core
# package.  The real EpisodeType is a string-enum; we mirror that here so
# tests can assert source=EpisodeType.message.
# ---------------------------------------------------------------------------


class _EpisodeType(str, Enum):
    message = "message"
    text = "text"
    json = "json"


class _EntityEdge:
    """Minimal stub for graphiti_core.nodes.EntityEdge used in MemoryForgetTool tests."""

    @staticmethod
    async def delete_by_uuids(driver: Any, uuids: list[str]) -> None:
        pass  # no-op in tests


def _ensure_graphiti_stubs() -> None:
    """Insert minimal stub modules into sys.modules if graphiti_core is absent."""
    if "graphiti_core" not in sys.modules:
        graphiti_core = types.ModuleType("graphiti_core")
        sys.modules["graphiti_core"] = graphiti_core

    if "graphiti_core.nodes" not in sys.modules:
        nodes_mod = types.ModuleType("graphiti_core.nodes")
        nodes_mod.EpisodeType = _EpisodeType  # type: ignore[attr-defined]
        nodes_mod.EntityEdge = _EntityEdge  # type: ignore[attr-defined]
        sys.modules["graphiti_core.nodes"] = nodes_mod
    else:
        # If the real package IS installed, expose our alias for test assertions.
        pass


_ensure_graphiti_stubs()

# Re-export EpisodeType so tests can import it from conftest if needed.
EpisodeType = sys.modules["graphiti_core.nodes"].EpisodeType


@pytest.fixture
def mock_graphiti():
    """A fully mocked Graphiti client."""
    g = MagicMock()
    g.build_indices_and_constraints = AsyncMock()
    g.add_episode = AsyncMock()
    g.search = AsyncMock(return_value=[])
    g.close = AsyncMock()
    g.driver = MagicMock()
    return g


@pytest.fixture
def mock_provider():
    """A minimal nanobot LLMProvider mock."""
    p = MagicMock()
    p.api_key = "test-key"
    p.api_base = "https://api.openai.com/v1"
    p.get_default_model.return_value = "gpt-4o-mini"
    return p


@pytest.fixture
def session_key():
    return "telegram:123456"
