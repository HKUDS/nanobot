from __future__ import annotations

import asyncio

import pytest

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.secure_registry import SecureToolRegistry
from nanobot.fitsec.types import OmegaLevel, PolicyDeniedError


class ExecTool(Tool):
    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "exec"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}

    async def execute(self, **kwargs) -> str:
        return f"OK:{kwargs['cmd']}"


def test_o2_denied_by_default() -> None:
    reg = SecureToolRegistry(strict_mode=True)
    reg.register(ExecTool(), omega_level=OmegaLevel.OMEGA_2)

    with pytest.raises(PolicyDeniedError):
        asyncio.run(reg.execute("exec", {"cmd": "echo hi"}))

    entries = reg.runtime.audit.get_entries(tool_id="exec")
    assert len(entries) == 1
    assert entries[0].executed is False


def test_o2_approval_allows() -> None:
    reg = SecureToolRegistry(strict_mode=True)
    reg.register(ExecTool(), omega_level=OmegaLevel.OMEGA_2)

    reg.runtime.policy.grant_omega2_approval("exec", duration_seconds=10.0)
    out = asyncio.run(reg.execute("exec", {"cmd": "echo hi"}))
    assert out == "OK:echo hi"

    entries = reg.runtime.audit.get_entries(tool_id="exec")
    assert len(entries) == 1
    assert entries[0].executed is True
