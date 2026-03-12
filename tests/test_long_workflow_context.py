"""Tests for first-phase long-workflow anti-forgetting support."""

from __future__ import annotations

from pathlib import Path

from nanobot.agent.context import ContextBuilder
from nanobot.session.manager import Session
from nanobot.utils.helpers import sync_workspace_templates


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    return workspace


def test_sync_workspace_templates_adds_pinned_and_workflow(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)

    added = sync_workspace_templates(workspace, silent=True)

    assert "memory/PINNED.md" in added
    assert "WORKFLOW.md" in added
    assert (workspace / "memory" / "PINNED.md").exists()
    assert (workspace / "WORKFLOW.md").exists()


def test_system_prompt_includes_pinned_and_workflow_context(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    (workspace / "memory").mkdir()
    (workspace / "memory" / "PINNED.md").write_text(
        "# Pinned\n- Always verify before claiming success.\n",
        encoding="utf-8",
    )
    (workspace / "WORKFLOW.md").write_text(
        "# Workflow\nCurrent step: implement pruning.\nNext step: run tests.\n",
        encoding="utf-8",
    )

    prompt = ContextBuilder(workspace).build_system_prompt()

    assert "# Pinned Context" in prompt
    assert "Always verify before claiming success." in prompt
    assert "# Current Workflow" in prompt
    assert "Current step: implement pruning." in prompt
    assert "Next step: run tests." in prompt


def test_get_history_prunes_older_tool_output_but_keeps_recent_detail() -> None:
    session = Session(key="cli:test")
    tool_payload = "line\n" * 120

    for idx in range(5):
        session.messages.extend([
            {"role": "user", "content": f"user-{idx}"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call-{idx}",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": f"call-{idx}",
                "name": "read_file",
                "content": f"tool-{idx}\n{tool_payload}",
            },
            {"role": "assistant", "content": f"done-{idx}"},
        ])

    history = session.get_history(max_messages=40)
    tool_messages = [m for m in history if m["role"] == "tool"]

    assert len(tool_messages) == 5
    assert tool_messages[0]["content"].startswith("[older tool result pruned: read_file]")
    assert "tool-0" in tool_messages[0]["content"]
    assert tool_messages[-1]["content"].startswith("tool-4\nline\nline")
    assert "[older tool result pruned" not in tool_messages[-1]["content"]
