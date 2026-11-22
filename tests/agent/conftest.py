from __future__ import annotations

import os
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.session_helpers import make_agent_loop
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider


@pytest.fixture
def cmd_python() -> str:
    """Return the Python command name available to ExecTool tests."""
    return "python" if os.name == "nt" else "python3"


def make_provider(
    default_model: str = "test-model",
    *,
    max_tokens: int = 4096,
    spec: bool = True,
) -> MagicMock:
    """Create a spec-limited LLM provider mock."""
    mock_type = MagicMock(spec=LLMProvider) if spec else MagicMock()
    provider = mock_type
    provider.get_default_model.return_value = default_model
    provider.generation = SimpleNamespace(
        max_tokens=max_tokens,
        temperature=0.1,
        reasoning_effort=None,
    )
    provider.estimate_prompt_tokens = MagicMock(return_value=(10_000, "test"))
    return provider


@pytest.fixture
def loop_factory(tmp_path: Path):
    def create(
        *, provider: LLMProvider | None = None, session_ttl_minutes: int = 0, patch_deps: bool = False,
    ) -> AgentLoop:
        build = partial(
            make_agent_loop, bus=MessageBus(), workspace=tmp_path, model="test-model", context_window_tokens=128_000,
            provider=provider if provider is not None else make_provider(), session_ttl_minutes=session_ttl_minutes,
        )
        if patch_deps:
            with patch("nanobot.agent.loop.SubagentManager") as subagents:
                subagents.return_value.cancel_by_session = AsyncMock(return_value=0)
                return build(context_builder=MagicMock(workspace=tmp_path))
        return build()

    return create
