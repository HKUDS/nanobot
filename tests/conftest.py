"""Shared fixtures for the full test suite."""

from __future__ import annotations

import pytest
from agent.runner_helpers import bind_default_attempt_route

from nanobot.agent.runner import AgentRunner


@pytest.fixture(autouse=True)
def provider_mocks_use_default_attempt_route(monkeypatch):
    """Keep legacy AgentRunner tests focused on behavior, not mock plumbing."""
    execute_provider_route = AgentRunner._execute_provider_route

    async def _execute(self, spec, *args, **kwargs):
        bind_default_attempt_route(spec.runtime.provider)
        return await execute_provider_route(self, spec, *args, **kwargs)

    monkeypatch.setattr(AgentRunner, "_execute_provider_route", _execute)
