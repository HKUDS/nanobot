from __future__ import annotations

import time

import pytest

from nanobot.fitsec.runtime import FitSecRuntime
from nanobot.fitsec.types import (
    OmegaLevel,
    ToolCall,
    ToolManifest,
    ToolNotRegisteredError,
    PolicyDeniedError,
)


def test_unregistered_tool_denied_and_audited() -> None:
    rt = FitSecRuntime(audit_path=None, strict_mode=True)

    call = ToolCall(tool_id="nope", action="execute", args={"x": 1})
    with pytest.raises(ToolNotRegisteredError):
        rt.execute(call)

    entries = rt.audit.get_entries(limit=1)
    assert len(entries) == 1
    assert entries[0].error == "ToolNotRegisteredError"


def test_o2_denied_by_default_and_audited() -> None:
    rt = FitSecRuntime(audit_path=None, strict_mode=True)

    rt.register_tool(
        ToolManifest(
            tool_id="exec",
            omega_level=OmegaLevel.OMEGA_2,
            description="dangerous",
            requires_approval=True,
        ),
        executor=lambda action, args: "OK",
    )

    call = ToolCall(tool_id="exec", action="execute", args={"cmd": "echo hi"})
    with pytest.raises(PolicyDeniedError):
        rt.execute(call)

    entries = rt.audit.get_entries(tool_id="exec")
    assert len(entries) == 1
    assert entries[0].executed is False
    assert entries[0].error == "PolicyDeniedError"


def test_o2_approval_allows_execution_and_audits() -> None:
    rt = FitSecRuntime(audit_path=None, strict_mode=True)

    rt.register_tool(
        ToolManifest(
            tool_id="exec",
            omega_level=OmegaLevel.OMEGA_2,
            description="dangerous",
            requires_approval=True,
        ),
        executor=lambda action, args: f"OK:{args.get('cmd')}",
    )

    rt.policy.grant_omega2_approval("exec", duration_seconds=10.0)

    call = ToolCall(tool_id="exec", action="execute", args={"cmd": "echo hi"})
    out = rt.execute(call)
    assert out == "OK:echo hi"

    entries = rt.audit.get_entries(tool_id="exec")
    assert len(entries) == 1
    assert entries[0].executed is True
    assert entries[0].error is None


def test_omega2_approval_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    rt = FitSecRuntime(audit_path=None, strict_mode=True)
    rt.register_tool(
        ToolManifest(
            tool_id="exec",
            omega_level=OmegaLevel.OMEGA_2,
            description="dangerous",
            requires_approval=True,
        ),
        executor=lambda action, args: "OK",
    )

    now = 1000.0
    monkeypatch.setattr(time, "time", lambda: now)

    rt.policy.grant_omega2_approval("exec", duration_seconds=0.01)
    now = 1000.02

    call = ToolCall(tool_id="exec", action="execute", args={})
    with pytest.raises(PolicyDeniedError):
        rt.execute(call)
