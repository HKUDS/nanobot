"""Global test fixtures — patches mem0 to avoid numpy FPE in CI/test environments."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from loguru import logger as _loguru_logger


def _noop_init_client(self):
    """Replace _Mem0Adapter._init_client with a no-op that leaves the adapter disabled."""
    self.enabled = False
    self.client = None
    self.mode = "disabled"
    self.error = "disabled-for-tests"


# Patch at import time so *every* MemoryStore construction skips the real
# mem0 initialisation (which pulls in HuggingFace / numpy and triggers an
# FPE on some platforms).
_patcher = patch(
    "nanobot.agent.memory.mem0_adapter._Mem0Adapter._init_client",
    _noop_init_client,
)
_patcher.start()


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
