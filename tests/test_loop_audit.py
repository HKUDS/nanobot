import json
from pathlib import Path

from nanobot.agent.loop import AgentLoop
from nanobot.config.schema import AuditConfig


def _mk_loop(audit_config: AuditConfig, workspace: Path) -> AgentLoop:
    loop = AgentLoop.__new__(AgentLoop)
    loop.workspace = workspace
    loop.audit_config = audit_config
    return loop


def test_audit_disabled_writes_nothing(tmp_path: Path) -> None:
    loop = _mk_loop(AuditConfig(enabled=False), tmp_path)
    loop._audit_tool_call("exec", {"command": "echo hi"}, "hi")
    assert not (tmp_path / "tool_audit.jsonl").exists()


def test_audit_enabled_writes_to_default_path(tmp_path: Path) -> None:
    loop = _mk_loop(AuditConfig(enabled=True), tmp_path)
    loop._audit_tool_call(
        "exec", {"command": "echo hi"}, "hi\n",
        tool_call_id="abc123", session_key="whatsapp:555",
    )

    audit_path = tmp_path / "tool_audit.jsonl"
    assert audit_path.exists()
    entry = json.loads(audit_path.read_text().strip())
    assert entry["tool"] == "exec"
    assert entry["arguments"] == {"command": "echo hi"}
    assert entry["result"] == "hi\n"
    assert entry["tool_call_id"] == "abc123"
    assert entry["session_key"] == "whatsapp:555"
    assert "timestamp" in entry


def test_audit_enabled_writes_to_custom_path(tmp_path: Path) -> None:
    custom = tmp_path / "custom_audit.jsonl"
    loop = _mk_loop(AuditConfig(enabled=True, path=str(custom)), tmp_path)
    loop._audit_tool_call("read_file", {"path": "/foo.txt"}, "file contents")

    assert custom.exists()
    assert not (tmp_path / "tool_audit.jsonl").exists()
    entry = json.loads(custom.read_text().strip())
    assert entry["tool"] == "read_file"


def test_audit_appends_multiple_calls(tmp_path: Path) -> None:
    loop = _mk_loop(AuditConfig(enabled=True), tmp_path)
    loop._audit_tool_call("exec", {"command": "cmd1"}, "out1", tool_call_id="id1", session_key="s1")
    loop._audit_tool_call("exec", {"command": "cmd2"}, "out2", tool_call_id="id2", session_key="s1")

    lines = (tmp_path / "tool_audit.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    first, second = json.loads(lines[0]), json.loads(lines[1])
    assert first["tool_call_id"] == "id1"
    assert second["tool_call_id"] == "id2"
    assert first["session_key"] == second["session_key"] == "s1"


def test_audit_null_session_and_call_id_when_omitted(tmp_path: Path) -> None:
    loop = _mk_loop(AuditConfig(enabled=True), tmp_path)
    loop._audit_tool_call("exec", {"command": "echo"}, "out")

    entry = json.loads((tmp_path / "tool_audit.jsonl").read_text().strip())
    assert entry["tool_call_id"] is None
    assert entry["session_key"] is None


def test_audit_survives_bad_path(tmp_path: Path) -> None:
    loop = _mk_loop(AuditConfig(enabled=True, path="/nonexistent/dir/audit.jsonl"), tmp_path)
    # Should not raise — failure is logged as a warning
    loop._audit_tool_call("exec", {"command": "echo"}, "out")
