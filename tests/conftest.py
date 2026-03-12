"""Global test fixtures — patches mem0 to avoid numpy FPE in CI/test environments."""

from __future__ import annotations

from unittest.mock import patch


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
