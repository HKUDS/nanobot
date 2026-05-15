"""Tests for the plan tool."""
from __future__ import annotations

import pytest

from nanobot.agent.tools.context import RequestContext
from nanobot.agent.tools.plan import PlanTool, _plan_session_key, _safe_filename


@pytest.fixture
def workspace(tmp_path):
    return str(tmp_path)


@pytest.fixture
def tool(workspace):
    return PlanTool(workspace=workspace)


@pytest.fixture
def ctx():
    return RequestContext(channel="cli", chat_id="test", session_key="cli:test")


def set_session(tool, key="cli:test"):
    _plan_session_key.set(key)


class TestSafeFilename:
    def test_alphanumeric(self):
        result = _safe_filename("hello")
        assert result.startswith("hello_")

    def test_colon_replaced(self):
        result = _safe_filename("cli:test")
        assert result.startswith("cli_test_")

    def test_long_key_truncated(self):
        assert len(_safe_filename("a" * 200)) <= 109

    def test_empty_falls_back(self):
        result = _safe_filename("")
        assert result.startswith("default_")


class TestCreate:
    async def test_create_plan(self, tool, ctx):
        set_session(tool)
        result = await tool.execute(action="create", title="Test Plan", goal="Fix the bug")
        assert "Plan created" in result
        assert "Test Plan" in result
        assert "Fix the bug" in result

    async def test_create_requires_title(self, tool):
        set_session(tool)
        result = await tool.execute(action="create", title="")
        assert "Error" in result

    async def test_create_with_steps(self, tool):
        set_session(tool)
        steps = '[{"text": "Step 1"}, {"text": "Step 2"}]'
        result = await tool.execute(action="create", title="Plan", steps=steps)
        assert "- [ ] Step 1" in result
        assert "- [ ] Step 2" in result

    async def test_create_rejects_duplicate(self, tool):
        set_session(tool)
        await tool.execute(action="create", title="Plan A")
        result = await tool.execute(action="create", title="Plan B")
        assert "already exists" in result


class TestUpdate:
    async def test_update_adds_notes(self, tool):
        set_session(tool)
        await tool.execute(action="create", title="Plan A")
        result = await tool.execute(action="update", notes="Found root cause")
        assert "Found root cause" in result
        assert "Notes" in result

    async def test_update_modifies_goal(self, tool):
        set_session(tool)
        await tool.execute(action="create", title="Plan A", goal="Original goal")
        result = await tool.execute(action="update", goal="New goal")
        assert "New goal" in result

    async def test_update_marks_steps(self, tool):
        set_session(tool)
        steps = '[{"text": "Read file"}, {"text": "Fix bug"}]'
        await tool.execute(action="create", title="Plan A", steps=steps)
        updated = '[{"status": "done"}, {"status": "active"}]'
        result = await tool.execute(action="update", steps=updated)
        assert "- [x] Read file" in result
        assert "- [>] Fix bug" in result

    async def test_update_appends_new_steps(self, tool):
        set_session(tool)
        steps = '[{"text": "Step 1"}]'
        await tool.execute(action="create", title="Plan A", steps=steps)
        new_steps = '[{"text": "Step 1"}, {"text": "Step 2"}, {"text": "Step 3"}]'
        result = await tool.execute(action="update", steps=new_steps)
        assert "Step 3" in result

    async def test_update_no_plan(self, tool):
        set_session(tool)
        result = await tool.execute(action="update", notes="No plan")
        assert "No active plan" in result


class TestShow:
    async def test_show_existing(self, tool):
        set_session(tool)
        await tool.execute(action="create", title="Plan A", goal="Do things")
        result = await tool.execute(action="show")
        assert "Plan A" in result

    async def test_show_no_plan(self, tool):
        set_session(tool)
        result = await tool.execute(action="show")
        assert "No active plan" in result


class TestDone:
    async def test_done_removes_plan(self, tool):
        set_session(tool)
        await tool.execute(action="create", title="Plan A")
        result = await tool.execute(action="done", reason="All done")
        assert "completed" in result.lower()
        # Plan should be gone
        result2 = await tool.execute(action="show")
        assert "No active plan" in result2

    async def test_done_no_plan(self, tool):
        set_session(tool)
        result = await tool.execute(action="done")
        assert "No active plan" in result


class TestSessionIsolation:
    async def test_different_sessions_separate_plans(self, tool):
        _plan_session_key.set("session:a")
        await tool.execute(action="create", title="Plan A")
        _plan_session_key.set("session:b")
        result = await tool.execute(action="show")
        assert "No active plan" in result
        await tool.execute(action="create", title="Plan B")
        _plan_session_key.set("session:a")
        result_a = await tool.execute(action="show")
        assert "Plan A" in result_a


class TestContextInjection:
    async def test_load_active_plan(self, workspace, tool):
        set_session(tool)
        await tool.execute(action="create", title="Test Plan", goal="Do things")
        plan = PlanTool.load_active_plan(workspace, "cli:test")
        assert plan is not None
        assert "Test Plan" in plan

    def test_load_no_plan(self, workspace):
        plan = PlanTool.load_active_plan(workspace, "nonexistent")
        assert plan is None


class TestSchema:
    def test_tool_schema_valid(self, tool):
        schema = tool.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "plan"
        params = schema["function"]["parameters"]
        assert "action" in params["properties"]
        assert params["properties"]["action"]["enum"] == ["create", "update", "show", "done"]

    def test_name_and_description(self, tool):
        assert tool.name == "plan"
        assert len(tool.description) > 10


class TestContextBuilderIntegration:
    def test_plan_injected_into_system_prompt(self, tmp_path):
        from nanobot.agent.context import ContextBuilder

        workspace = tmp_path
        plans_dir = workspace / "memory" / "plans"
        plans_dir.mkdir(parents=True)
        (plans_dir / f"{_safe_filename('cli:test')}.md").write_text(
            "# Plan: Test\nGoal: Do stuff\n## Steps\n- [x] Step 1\n- [ ] Step 2",
            encoding="utf-8",
        )

        builder = ContextBuilder(workspace=workspace)
        prompt = builder.build_system_prompt(session_key="cli:test")
        assert "Active Plan" in prompt
        assert "Test" in prompt
        assert "Step 1" in prompt

    def test_no_plan_no_injection(self, tmp_path):
        from nanobot.agent.context import ContextBuilder

        builder = ContextBuilder(workspace=tmp_path)
        prompt = builder.build_system_prompt(session_key="cli:no_plan")
        assert "Active Plan" not in prompt

    def test_plan_in_full_messages(self, tmp_path):
        from nanobot.agent.context import ContextBuilder

        plans_dir = tmp_path / "memory" / "plans"
        plans_dir.mkdir(parents=True)
        (plans_dir / f"{_safe_filename('cli:test')}.md").write_text(
            "# Plan: Integration Test\nGoal: Verify injection",
            encoding="utf-8",
        )

        builder = ContextBuilder(workspace=tmp_path)
        messages = builder.build_messages(
            history=[], current_message="hello", session_key="cli:test"
        )
        system = messages[0]["content"]
        assert "Active Plan" in system
        assert "Integration Test" in system
