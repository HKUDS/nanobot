"""Tests for the plan tool."""
from __future__ import annotations

import json

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

    def test_similar_keys_dont_collide(self):
        assert _safe_filename("cli:test:1") != _safe_filename("cli:test:2")

    def test_unicode_normalized(self):
        assert _safe_filename("café") != _safe_filename("cafe")

    def test_collision_resistance(self):
        keys = [f"session:{i}" for i in range(100)]
        filenames = [_safe_filename(k) for k in keys]
        assert len(set(filenames)) == len(keys)


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
        result = await tool.execute(
            action="create", title="Plan",
            steps=[{"text": "Step 1"}, {"text": "Step 2"}],
        )
        assert "- [ ] Step 1" in result
        assert "- [ ] Step 2" in result

    async def test_create_rejects_duplicate(self, tool):
        set_session(tool)
        await tool.execute(action="create", title="Plan A")
        result = await tool.execute(action="create", title="Plan B")
        assert "already exists" in result

    async def test_create_title_only(self, tool):
        set_session(tool)
        result = await tool.execute(action="create", title="Minimal Plan")
        assert "Plan created" in result
        assert "Minimal Plan" in result
        assert "Goal" not in result
        assert "## Steps" not in result

    async def test_create_stores_json(self, tool, workspace):
        from pathlib import Path
        set_session(tool)
        await tool.execute(action="create", title="JSON Test", goal="Verify storage")
        plans_dir = Path(workspace) / "memory" / "plans"
        json_files = list(plans_dir.glob("*.json"))
        assert len(json_files) == 1
        data = json.loads(json_files[0].read_text())
        assert data["title"] == "JSON Test"
        assert data["goal"] == "Verify storage"


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
        await tool.execute(
            action="create", title="Plan A",
            steps=[{"text": "Read file"}, {"text": "Fix bug"}],
        )
        result = await tool.execute(
            action="update",
            steps=[{"text": "Read file", "status": "done"}, {"status": "active"}],
        )
        assert "- [x] Read file" in result
        assert "- [>] Fix bug" in result

    async def test_update_appends_new_steps(self, tool):
        set_session(tool)
        await tool.execute(
            action="create", title="Plan A",
            steps=[{"text": "Step 1"}],
        )
        result = await tool.execute(
            action="update",
            steps=[{"text": "Step 1"}, {"text": "Step 2"}, {"text": "Step 3"}],
        )
        assert "Step 3" in result

    async def test_update_no_plan(self, tool):
        set_session(tool)
        result = await tool.execute(action="update", notes="No plan")
        assert "No active plan" in result

    async def test_update_steps_and_notes_together(self, tool):
        set_session(tool)
        await tool.execute(
            action="create", title="Plan A",
            steps=[{"text": "Step 1"}, {"text": "Step 2"}],
        )
        result = await tool.execute(
            action="update",
            steps=[{"status": "done"}, {"status": "active"}],
            notes="Halfway there",
        )
        assert "- [x] Step 1" in result
        assert "- [>] Step 2" in result
        assert "Halfway there" in result

    async def test_update_notes_no_duplicate_heading(self, tool):
        set_session(tool)
        await tool.execute(action="create", title="Plan A")
        await tool.execute(action="update", notes="First note")
        result = await tool.execute(action="update", notes="Second note")
        assert result.count("## Notes") == 1
        assert "First note" in result
        assert "Second note" in result

    async def test_update_adds_goal_to_plan_without_goal(self, tool):
        set_session(tool)
        await tool.execute(action="create", title="Plan A")
        result = await tool.execute(action="update", goal="New goal")
        assert "New goal" in result
        assert "Goal: New goal" in result

    async def test_update_adds_steps_before_notes(self, tool):
        set_session(tool)
        await tool.execute(action="create", title="Plan A")
        await tool.execute(action="update", notes="A note")
        result = await tool.execute(action="update", steps=[{"text": "Step 1"}])
        steps_idx = result.index("## Steps")
        notes_idx = result.index("## Notes")
        assert steps_idx < notes_idx

    async def test_update_filters_empty_text_steps(self, tool):
        set_session(tool)
        result = await tool.execute(
            action="create", title="Plan A",
            steps=[{"text": "Step 1"}, {"text": ""}],
        )
        assert "- [ ] Step 1" in result
        assert result.count("- [ ]") == 1


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
    async def test_done_archives_plan(self, tool, workspace):
        set_session(tool)
        await tool.execute(action="create", title="Plan A")
        result = await tool.execute(action="done", reason="All done")
        assert "archived" in result.lower()
        assert "completed" in result.lower()
        # Plan should be gone from active
        result2 = await tool.execute(action="show")
        assert "No active plan" in result2

    async def test_done_no_plan(self, tool):
        set_session(tool)
        result = await tool.execute(action="done")
        assert "No active plan" in result

    async def test_archived_plan_has_completed_timestamp(self, tool, workspace):
        from pathlib import Path
        set_session(tool)
        await tool.execute(action="create", title="Timestamped")
        await tool.execute(action="done")
        archive_dir = Path(workspace) / "memory" / "plans" / "archive"
        archive_files = list(archive_dir.glob("*.json"))
        assert len(archive_files) == 1
        data = json.loads(archive_files[0].read_text())
        assert "completed" in data
        assert data["completed"] is not None


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
        assert params["properties"]["steps"]["type"] == "array"

    def test_name_and_description(self, tool):
        assert tool.name == "plan"
        assert len(tool.description) > 10


class TestRuntimeContextProvider:
    async def test_provider_returns_plan_when_exists(self, tool):
        set_session(tool)
        await tool.execute(action="create", title="Test Plan", goal="Do things")
        provider = tool.runtime_context_provider()
        result = provider("cli:test")
        assert result is not None
        assert "Test Plan" in result
        assert "Do things" in result

    def test_provider_returns_none_when_no_plan(self, tool):
        provider = tool.runtime_context_provider()
        result = provider("nonexistent")
        assert result is None

    def test_provider_returns_none_for_empty_session_key(self, tool):
        provider = tool.runtime_context_provider()
        result = provider(None)
        assert result is None


class TestContextBuilderIntegration:
    @staticmethod
    def _make_plan_dir(tmp_path, plan_data):
        plans_dir = tmp_path / "memory" / "plans"
        plans_dir.mkdir(parents=True)
        (plans_dir / f"{_safe_filename('cli:test')}.json").write_text(
            json.dumps(plan_data), encoding="utf-8",
        )
        return plans_dir

    def test_plan_injected_into_runtime_context(self, tmp_path):
        from nanobot.agent.context import ContextBuilder

        plan_data = {
            "title": "Test",
            "goal": "Do stuff",
            "steps": [{"text": "Step 1", "status": "done"}, {"text": "Step 2", "status": "pending"}],
            "notes": [],
            "created": "2025-01-01T00:00:00Z",
            "updated": None,
        }
        self._make_plan_dir(tmp_path, plan_data)

        builder = ContextBuilder(workspace=tmp_path)
        assert "Active Plan" not in builder.build_system_prompt()

        def _provider(session_key):
            if session_key == "cli:test":
                return "# Active Plan\n\n" + PlanTool.render_markdown(plan_data)
            return None

        builder.register_runtime_context_provider(_provider)
        messages = builder.build_messages(
            history=[], current_message="hello", session_key="cli:test"
        )
        # Plan in user message (runtime context), not system prompt
        assert "Active Plan" not in messages[0]["content"]
        user_content = messages[-1]["content"]
        assert "Active Plan" in user_content
        assert "Test" in user_content
        assert "Step 1" in user_content

    def test_no_plan_no_injection(self, tmp_path):
        from nanobot.agent.context import ContextBuilder

        builder = ContextBuilder(workspace=tmp_path)
        messages = builder.build_messages(
            history=[], current_message="hello", session_key="cli:no_plan"
        )
        assert "Active Plan" not in messages[-1]["content"]


class TestSpecialCharacters:
    async def test_title_with_markdown(self, tool):
        set_session(tool)
        result = await tool.execute(
            action="create",
            title="Plan ## Not a heading",
            goal="Goal with ```code``` and **bold**",
        )
        assert "Plan created" in result
        show = await tool.execute(action="show")
        assert "Not a heading" in show
        assert "**bold**" in show

    async def test_step_with_special_chars(self, tool):
        set_session(tool)
        result = await tool.execute(
            action="create", title="Test",
            steps=[{"text": "Fix bug in `foo.bar` [critical]"}],
        )
        assert "`foo.bar`" in result
        assert "[critical]" in result


class TestStatusNormalization:
    async def test_unknown_status_clamped_to_pending(self, tool):
        set_session(tool)
        result = await tool.execute(
            action="create", title="Test",
            steps=[{"text": "Step 1", "status": "unknown"}],
        )
        assert "- [ ] Step 1" in result

    async def test_valid_statuses_preserved(self, tool):
        set_session(tool)
        result = await tool.execute(
            action="create", title="Test",
            steps=[
                {"text": "A", "status": "pending"},
                {"text": "B", "status": "active"},
                {"text": "C", "status": "done"},
                {"text": "D", "status": "blocked"},
            ],
        )
        assert "- [ ] A" in result
        assert "- [>] B" in result
        assert "- [x] C" in result
        assert "- [!] D" in result
