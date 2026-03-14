from __future__ import annotations

import asyncio
import json

import pytest

from nanobot.agent.team import TeamManager
from nanobot.agent.team import board, mailbox
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse
from nanobot.session.manager import SessionManager


class ScriptedProvider:
    def __init__(self, contents: list[str]):
        self.contents = contents
        self.idx = 0

    def get_default_model(self) -> str:
        return "test-model"

    async def chat_with_retry(self, **kwargs):
        if not self.contents:
            return LLMResponse(content="{}")
        content = self.contents[min(self.idx, len(self.contents) - 1)]
        self.idx += 1
        return LLMResponse(content=content)

    async def chat(self, **kwargs):
        return LLMResponse(content="ok")


def _manager(tmp_path, provider: ScriptedProvider) -> TeamManager:
    return TeamManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        sessions=SessionManager(tmp_path),
        worker_max_iterations=0,
    )


def _valid_plan(mission: str = "ship it") -> str:
    return json.dumps(
        {
            "mission": mission,
            "members": [
                {"name": "researcher", "role": "analysis"},
                {"name": "builder", "role": "delivery"},
            ],
            "tasks": [
                {"id": "t1", "title": "Analyze", "description": "Study requirements", "owner": "researcher"},
                {
                    "id": "t2",
                    "title": "Implement",
                    "description": "Deliver output",
                    "owner": "builder",
                    "depends_on": ["t1"],
                },
            ],
            "notes": "# Team Notes",
        }
    )


def test_validate_plan_payload_rejects_duplicate_members(tmp_path):
    mgr = _manager(tmp_path, ScriptedProvider([_valid_plan()]))
    payload = {
        "mission": "x",
        "members": [{"name": "a", "role": "r1"}, {"name": "A", "role": "r2"}],
        "tasks": [{"id": "t1", "title": "x", "description": ""}],
    }
    _, err = mgr._validate_plan_payload(payload, "x")
    assert err == "duplicate member names"


def test_validate_plan_payload_rejects_empty_tasks(tmp_path):
    mgr = _manager(tmp_path, ScriptedProvider([_valid_plan()]))
    payload = {"mission": "x", "members": [{"name": "a", "role": "r1"}, {"name": "b", "role": "r2"}], "tasks": []}
    _, err = mgr._validate_plan_payload(payload, "x")
    assert err == "tasks must be a non-empty list"


def test_validate_plan_payload_rejects_cyclic_dependencies(tmp_path):
    mgr = _manager(tmp_path, ScriptedProvider([_valid_plan()]))
    payload = {
        "mission": "x",
        "members": [{"name": "a", "role": "r1"}, {"name": "b", "role": "r2"}],
        "tasks": [
            {"id": "t1", "title": "A", "description": "", "depends_on": ["t2"]},
            {"id": "t2", "title": "B", "description": "", "depends_on": ["t1"]},
        ],
    }
    _, err = mgr._validate_plan_payload(payload, "x")
    assert err == "task dependency graph has a cycle"


@pytest.mark.asyncio
async def test_start_mode_falls_back_on_malformed_planner_output(tmp_path):
    mgr = _manager(tmp_path, ScriptedProvider(["not-json", "still-not-json"]))
    text = await mgr.start_or_route_goal("cli:room1", "deliver feature")
    assert "Nano team started" in text

    run_dir = mgr.get_team_dir("cli:room1")
    assert run_dir is not None
    assert (run_dir / "config.json").exists()
    assert (run_dir / "tasks.json").exists()
    assert (run_dir / "mailbox.jsonl").exists() is False
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "NOTES.md").exists()
    assert (run_dir / "workers").exists()

    state = mgr.get_team_state("cli:room1")
    assert state is not None
    assert len(state.members) == 2


@pytest.mark.asyncio
async def test_two_sessions_are_isolated(tmp_path):
    provider = ScriptedProvider([_valid_plan("a"), _valid_plan("b")])
    mgr = _manager(tmp_path, provider)
    await asyncio.gather(
        mgr.start_or_route_goal("cli:a", "goal-a"),
        mgr.start_or_route_goal("cli:b", "goal-b"),
    )
    assert mgr.is_active("cli:a")
    assert mgr.is_active("cli:b")
    assert mgr.get_team_dir("cli:a") != mgr.get_team_dir("cli:b")


@pytest.mark.asyncio
async def test_lifecycle_status_log_and_auto_reattach(tmp_path):
    provider = ScriptedProvider(
        [
            _valid_plan("mission-1"),
            json.dumps({"tasks": [{"title": "Follow-up", "description": "Do more", "owner": "builder"}]}),
        ]
    )
    mgr = _manager(tmp_path, provider)
    session_key = "cli:demo"

    await mgr.start_or_route_goal(session_key, "initial objective")
    routed = await mgr.route_user_message(session_key, "please continue")
    assert "Queued" in routed

    log_text = mgr.log_text(session_key)
    assert "team_started" in log_text
    assert "task_added" in log_text

    stop_snapshot = await mgr.stop_mode(session_key, with_snapshot=True)
    assert "Team Lead Final Summary" in stop_snapshot
    assert not mgr.is_active(session_key)

    status = mgr.status_text(session_key)
    assert "Team `" in status
    assert mgr.is_active(session_key)


@pytest.mark.asyncio
async def test_handle_approval_reply_approve(tmp_path):
    mgr = _manager(tmp_path, ScriptedProvider([_valid_plan("mission-approval")]))
    session_key = "telegram:demo"
    await mgr.start_or_route_goal(session_key, "approval flow")
    run_dir = mgr.get_team_dir(session_key)
    assert run_dir is not None
    board.submit_plan(run_dir, "t1", "Plan A")

    reply = mgr.handle_approval_reply(session_key, "批准 t1")
    assert reply == "Updated task t1 to in_progress"
    updated = next(t for t in board.load(run_dir) if t.id == "t1")
    assert updated.status == "in_progress"


@pytest.mark.asyncio
async def test_handle_approval_reply_manual_change(tmp_path):
    mgr = _manager(tmp_path, ScriptedProvider([_valid_plan("mission-manual")]))
    session_key = "telegram:demo2"
    await mgr.start_or_route_goal(session_key, "manual approval flow")
    run_dir = mgr.get_team_dir(session_key)
    assert run_dir is not None
    board.submit_plan(run_dir, "t1", "Initial Plan")

    reply = mgr.handle_approval_reply(session_key, "补充 t1 请增加风险分析")
    assert reply == "Requested changes for t1."
    updated = next(t for t in board.load(run_dir) if t.id == "t1")
    assert updated.status == "planning"
    mails = mailbox.recent(run_dir, n=5)
    assert any("Please revise t1" in m.content for m in mails)
