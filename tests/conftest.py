"""Global test fixtures."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from loguru import logger as _loguru_logger

from nanobot.providers.base import LLMProvider, LLMResponse


class FakeProvider(LLMProvider):
    """Scripted LLM provider for tests — cycles through a fixed list of responses."""

    def __init__(self, responses: list[str] | None = None) -> None:
        super().__init__()
        self._responses = responses or ['{"role": "general"}']
        self._idx = 0

    def get_default_model(self) -> str:
        return "fake-model"

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        text = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return LLMResponse(content=text)


@pytest.fixture(autouse=True)
def _restore_loguru_namespaces():
    """Undo any ``logger.disable(...)`` side effects from CLI tests.

    CLI command functions call ``logger.disable("nanobot")`` as a side effect
    of being invoked via ``runner.invoke``.  Because loguru is a module-level
    singleton, that disable persists into subsequent tests.  This cheap fixture
    re-enables the namespace before every test so log-capture tests are not
    affected by test ordering.
    """
    _loguru_logger.enable("nanobot")
    yield


@pytest.fixture()
def minimal_tool_registry():
    """A bare ToolRegistry with no tools registered."""
    from nanobot.agent.tools.registry import ToolRegistry

    return ToolRegistry()


@pytest.fixture()
def propagate_loguru_to_caplog(caplog):
    """Route loguru output through stdlib logging so pytest ``caplog`` can capture it.

    Apply this fixture explicitly to test classes/functions that use ``caplog``
    to assert on log output from loguru-based modules.
    """

    class _PropagateHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            logging.getLogger(record.name).handle(record)

    handler_id = _loguru_logger.add(
        _PropagateHandler(),
        format="{message}",
    )
    yield
    _loguru_logger.remove(handler_id)
