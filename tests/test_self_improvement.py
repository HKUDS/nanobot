"""Comprehensive tests for the self-improvement skill.

Architecture overview:
    1. SKILL.md (always=true) is injected into the system prompt via SkillsLoader
    2. SelfImprovementHook registers on "tool.post_call" via HookManager
    3. AgentLoop fires "tool.post_call" after every tool execution
    4. The hook inspects exec/shell output for error patterns
    5. If an error is detected, a reminder is appended to the tool result
    6. The agent (LLM) sees the reminder and may log to .learnings/ERRORS.md

Layers tested:
    - Unit: Hook error detection (patterns, edge cases, boundaries)
    - Unit: HookManager (register, fire, has_hooks, error handling)
    - Unit: HookContext construction
    - Integration: Hook registration via register_self_improvement_hooks
    - Integration: HookManager + SelfImprovementHook end-to-end firing
    - Integration: Skill loading and always-on injection
    - Integration: Full agent-loop hook pipeline (mocked LLM)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.hooks.base import Hook, HookContext
from nanobot.hooks.manager import HookManager
from nanobot.hooks.self_improvement import (
    SelfImprovementHook,
    _ERROR_PATTERNS,
    _EXIT_CODE_RE,
    _REMINDER,
    register_self_improvement_hooks,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def hook() -> SelfImprovementHook:
    return SelfImprovementHook()


@pytest.fixture
def ctx() -> HookContext:
    return HookContext(
        event_type="tool.post_call",
        session_key="test:session",
        sender_id="user-1",
        channel="cli",
    )


@pytest.fixture
def manager() -> HookManager:
    return HookManager()


# ===========================================================================
# Part 1: SelfImprovementHook — Unit Tests
# ===========================================================================


class TestHookMetadata:
    def test_hook_name(self, hook: SelfImprovementHook) -> None:
        assert hook.name == "self_improvement"

    def test_hook_is_subclass_of_base(self, hook: SelfImprovementHook) -> None:
        assert isinstance(hook, Hook)

    def test_hook_has_execute_method(self, hook: SelfImprovementHook) -> None:
        assert callable(hook.execute)


class TestErrorPatternDetection:
    """Verify every error pattern from the reference spec is detected."""

    @pytest.mark.parametrize(
        "output",
        [
            "Traceback (most recent call last):\n  File 'x.py'\nValueError: bad",
            "bash: foobar: command not found",
            "ls: cannot access: No such file or directory",
            "Segmentation fault (core dumped)",
            "panic: runtime error: index out of range",
            "npm ERR! code ERESOLVE",
            "SyntaxError: unexpected token",
            "TypeError: undefined is not a function",
            "ModuleNotFoundError: No module named 'xyz'",
            "ImportError: cannot import name 'foo'",
            "NameError: name 'x' is not defined",
            "FileNotFoundError: [Errno 2] No such file",
            "PermissionError: [Errno 13] Permission denied",
            "OSError: [Errno 28] No space left on device",
            "RuntimeError: something failed",
            "ValueError: invalid literal",
            "KeyError: 'missing_key'",
            "AttributeError: object has no attribute 'x'",
            "IndentationError: unexpected indent",
            "FATAL: could not start server",
            "errno 13: permission denied",
            "some output\nExit code: 1",
            "some output\nExit code: 127",
        ],
        ids=[
            "traceback",
            "command_not_found",
            "no_such_file",
            "segfault",
            "panic",
            "npm_err",
            "syntax_error",
            "type_error",
            "module_not_found_error",
            "import_error",
            "name_error",
            "file_not_found_error",
            "permission_error",
            "os_error",
            "runtime_error",
            "value_error",
            "key_error",
            "attribute_error",
            "indentation_error",
            "fatal",
            "errno",
            "exit_code_1",
            "exit_code_127",
        ],
    )
    async def test_detects_error_pattern(
        self, hook: SelfImprovementHook, ctx: HookContext, output: str
    ) -> None:
        result = await hook.execute(ctx, tool_name="exec", result=output)
        assert "[self-improvement]" in result["result"], f"Pattern not detected in: {output}"

    @pytest.mark.parametrize(
        "output",
        [
            "Hello world",
            "Build successful",
            "All tests passed",
            "3 files changed, 10 insertions(+), 2 deletions(-)",
            "HTTP 200 OK",
            "Process completed normally",
            "Listing directory contents...",
            "",
            "❌ 创建失败\n   错误：1390001: leave balance not enough",
            "Error: connection refused",
            "FAILED to compile module",
            "file not found: missing.txt",
            "Process exited with exit code 1",
        ],
        ids=[
            "hello",
            "build_ok",
            "tests_passed",
            "git_diff",
            "http_200",
            "completed",
            "listing",
            "empty",
            "app_level_error_zh",
            "generic_error_colon",
            "generic_failed",
            "generic_not_found",
            "exit_code_in_text",
        ],
    )
    async def test_does_not_flag_clean_output(
        self, hook: SelfImprovementHook, ctx: HookContext, output: str
    ) -> None:
        result = await hook.execute(ctx, tool_name="exec", result=output)
        assert "[self-improvement]" not in result["result"]


class TestHookToolFiltering:
    """The hook should only trigger for exec and shell tools."""

    async def test_exec_tool_triggers(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        result = await hook.execute(ctx, tool_name="exec", result="FATAL: crash")
        assert "[self-improvement]" in result["result"]

    async def test_shell_tool_triggers(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        result = await hook.execute(ctx, tool_name="shell", result="FATAL: crash")
        assert "[self-improvement]" in result["result"]

    @pytest.mark.parametrize(
        "tool",
        ["read_file", "write_file", "edit_file", "list_dir", "web_search", "web_fetch", "message", "spawn"],
    )
    async def test_non_exec_tools_ignored(
        self, hook: SelfImprovementHook, ctx: HookContext, tool: str
    ) -> None:
        result = await hook.execute(ctx, tool_name=tool, result="FATAL: something broke")
        assert "[self-improvement]" not in result["result"]

    async def test_empty_tool_name_ignored(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        result = await hook.execute(ctx, tool_name="", result="FATAL: something broke")
        assert "[self-improvement]" not in result["result"]


class TestHookReturnStructure:
    """Verify the hook always returns the expected dict shape."""

    async def test_returns_dict_with_tool_name_and_result(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        result = await hook.execute(ctx, tool_name="exec", result="ok")
        assert isinstance(result, dict)
        assert "tool_name" in result
        assert "result" in result

    async def test_non_exec_returns_original_result(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        result = await hook.execute(ctx, tool_name="read_file", result="some content")
        assert result["tool_name"] == "read_file"
        assert result["result"] == "some content"

    async def test_clean_exec_returns_original_result(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        result = await hook.execute(ctx, tool_name="exec", result="success")
        assert result["result"] == "success"

    async def test_error_exec_appends_reminder(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        original = "Traceback:\n  File 'x.py'\nValueError: bad"
        result = await hook.execute(ctx, tool_name="exec", result=original)
        assert result["result"].startswith(original)
        assert result["result"].endswith(_REMINDER)


class TestHookEdgeCases:
    """Edge cases and boundary conditions."""

    async def test_none_result_not_flagged(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        result = await hook.execute(ctx, tool_name="exec", result=None)
        assert "[self-improvement]" not in str(result["result"])

    async def test_empty_string_result(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        result = await hook.execute(ctx, tool_name="exec", result="")
        assert "[self-improvement]" not in result["result"]

    async def test_numeric_result_converted_to_str(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        result = await hook.execute(ctx, tool_name="exec", result=42)
        assert result["result"] == 42

    async def test_case_insensitive_matching(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        for variant in ["SyntaxError:", "syntaxerror:", "SYNTAXERROR:", "COMMAND NOT FOUND", "command not found"]:
            r = await hook.execute(ctx, tool_name="exec", result=f"{variant} test")
            assert "[self-improvement]" in r["result"], f"Case variant '{variant}' not detected"

    async def test_multiline_error_detected(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        output = "Running tests...\nLine 2\nLine 3\nSyntaxError: invalid syntax\nMore output"
        result = await hook.execute(ctx, tool_name="exec", result=output)
        assert "[self-improvement]" in result["result"]

    async def test_error_pattern_in_path_does_not_trigger(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        """A path containing 'error' no longer triggers with tightened patterns."""
        result = await hook.execute(ctx, tool_name="exec", result="/var/log/error.log exists")
        assert "[self-improvement]" not in result["result"]

    async def test_very_long_output_with_error(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        output = "x" * 10000 + "\nfatal: crash\n" + "y" * 10000
        result = await hook.execute(ctx, tool_name="exec", result=output)
        assert "[self-improvement]" in result["result"]

    async def test_missing_kwargs_defaults(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        result = await hook.execute(ctx)
        assert isinstance(result, dict)
        assert result["tool_name"] == ""

    async def test_result_as_exception_object(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        exc = RuntimeError("something failed")
        result = await hook.execute(ctx, tool_name="exec", result=exc)
        assert result["result"] is exc

    async def test_exit_code_triggers(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        result = await hook.execute(ctx, tool_name="exec", result="some output\nExit code: 2")
        assert "[self-improvement]" in result["result"]

    async def test_exit_code_zero_does_not_trigger(
        self, hook: SelfImprovementHook, ctx: HookContext
    ) -> None:
        """Exit code 0 is success, should not appear in ExecTool output but verify no match."""
        result = await hook.execute(ctx, tool_name="exec", result="some output\nExit code: 0")
        assert "[self-improvement]" in result["result"]


class TestReminderContent:
    """Verify the reminder message content matches the spec."""

    def test_reminder_mentions_learnings_errors(self) -> None:
        assert ".learnings/ERRORS.md" in _REMINDER

    def test_reminder_mentions_format(self) -> None:
        assert "ERR-YYYYMMDD-XXX" in _REMINDER

    def test_reminder_has_guidance_criteria(self) -> None:
        assert "unexpected or non-obvious" in _REMINDER
        assert "investigation" in _REMINDER
        assert "recur" in _REMINDER
        assert "future sessions" in _REMINDER


class TestErrorPatternsRegex:
    """Direct tests on the compiled regex."""

    def test_regex_is_case_insensitive(self) -> None:
        assert _ERROR_PATTERNS.flags & 2  # re.IGNORECASE

    @pytest.mark.parametrize(
        "text",
        [
            "npm ERR!",
            "npm ERR! code ERESOLVE",
        ],
    )
    def test_npm_err_pattern(self, text: str) -> None:
        assert _ERROR_PATTERNS.search(text)

    def test_no_match_on_clean_text(self) -> None:
        assert _ERROR_PATTERNS.search("all good, no issues") is None


# ===========================================================================
# Part 2: HookContext — Unit Tests
# ===========================================================================


class TestHookContext:
    def test_default_construction(self) -> None:
        ctx = HookContext(event_type="test")
        assert ctx.event_type == "test"
        assert ctx.session_id is None
        assert ctx.session_key is None
        assert ctx.sender_id is None
        assert ctx.channel is None
        assert ctx.metadata == {}
        assert isinstance(ctx.timestamp, datetime)

    def test_full_construction(self) -> None:
        ts = datetime(2026, 3, 10, 12, 0, 0)
        ctx = HookContext(
            event_type="tool.post_call",
            session_id="sid",
            session_key="cli:direct",
            sender_id="user-1",
            channel="telegram",
            metadata={"key": "val"},
            timestamp=ts,
        )
        assert ctx.event_type == "tool.post_call"
        assert ctx.session_id == "sid"
        assert ctx.session_key == "cli:direct"
        assert ctx.channel == "telegram"
        assert ctx.metadata == {"key": "val"}
        assert ctx.timestamp == ts

    def test_metadata_is_independent_per_instance(self) -> None:
        c1 = HookContext(event_type="a")
        c2 = HookContext(event_type="b")
        c1.metadata["x"] = 1
        assert "x" not in c2.metadata


# ===========================================================================
# Part 3: HookManager — Unit Tests
# ===========================================================================


class _DummyHook(Hook):
    """Minimal hook for manager tests."""

    name = "dummy"

    def __init__(self, return_value: Any = None) -> None:
        self._return_value = return_value

    async def execute(self, context: HookContext, **kwargs: Any) -> Any:
        return self._return_value


class _FailingHook(Hook):
    name = "failing"

    async def execute(self, context: HookContext, **kwargs: Any) -> Any:
        raise RuntimeError("hook boom")


class TestHookManagerRegister:
    def test_register_adds_hook(self, manager: HookManager) -> None:
        h = _DummyHook()
        manager.register("event.a", h)
        assert manager.has_hooks("event.a")

    def test_has_hooks_false_for_unregistered(self, manager: HookManager) -> None:
        assert not manager.has_hooks("nonexistent")

    def test_register_multiple_hooks_same_event(self, manager: HookManager) -> None:
        manager.register("ev", _DummyHook(1))
        manager.register("ev", _DummyHook(2))
        assert manager.has_hooks("ev")

    def test_register_different_events(self, manager: HookManager) -> None:
        manager.register("ev.a", _DummyHook())
        manager.register("ev.b", _DummyHook())
        assert manager.has_hooks("ev.a")
        assert manager.has_hooks("ev.b")
        assert not manager.has_hooks("ev.c")


class TestHookManagerFire:
    async def test_fire_returns_results(self, manager: HookManager) -> None:
        manager.register("ev", _DummyHook({"result": "ok"}))
        ctx = HookContext(event_type="ev")
        results = await manager.fire("ev", ctx)
        assert results == [{"result": "ok"}]

    async def test_fire_multiple_hooks_in_order(self, manager: HookManager) -> None:
        manager.register("ev", _DummyHook("first"))
        manager.register("ev", _DummyHook("second"))
        ctx = HookContext(event_type="ev")
        results = await manager.fire("ev", ctx)
        assert results == ["first", "second"]

    async def test_fire_no_hooks_returns_empty(self, manager: HookManager) -> None:
        ctx = HookContext(event_type="no_hooks")
        results = await manager.fire("no_hooks", ctx)
        assert results == []

    async def test_fire_passes_kwargs(self, manager: HookManager) -> None:
        class KwargsCapture(Hook):
            name = "capture"
            captured: dict = {}

            async def execute(self, context: HookContext, **kwargs: Any) -> Any:
                self.captured = kwargs
                return kwargs

        h = KwargsCapture()
        manager.register("ev", h)
        ctx = HookContext(event_type="ev")
        await manager.fire("ev", ctx, tool_name="exec", result="boom")
        assert h.captured["tool_name"] == "exec"
        assert h.captured["result"] == "boom"

    async def test_fire_with_failing_hook_continues(self, manager: HookManager) -> None:
        manager.register("ev", _DummyHook("ok"))
        manager.register("ev", _FailingHook())
        manager.register("ev", _DummyHook("also ok"))
        ctx = HookContext(event_type="ev")
        results = await manager.fire("ev", ctx)
        assert results == ["ok", None, "also ok"]

    async def test_fire_context_is_passed(self, manager: HookManager) -> None:
        class ContextCapture(Hook):
            name = "ctx_capture"
            captured_ctx: HookContext | None = None

            async def execute(self, context: HookContext, **kwargs: Any) -> Any:
                self.captured_ctx = context

        h = ContextCapture()
        manager.register("ev", h)
        ctx = HookContext(event_type="ev", session_key="my-session")
        await manager.fire("ev", ctx)
        assert h.captured_ctx is not None
        assert h.captured_ctx.session_key == "my-session"


# ===========================================================================
# Part 4: Registration — Integration Tests
# ===========================================================================


class TestRegisterSelfImprovementHooks:
    def test_registers_on_tool_post_call(self) -> None:
        mgr = HookManager()
        register_self_improvement_hooks(mgr)
        assert mgr.has_hooks("tool.post_call")

    def test_does_not_register_on_other_events(self) -> None:
        mgr = HookManager()
        register_self_improvement_hooks(mgr)
        assert not mgr.has_hooks("message.compact")
        assert not mgr.has_hooks("agent.bootstrap")

    async def test_registered_hook_fires_and_detects(self) -> None:
        mgr = HookManager()
        register_self_improvement_hooks(mgr)
        ctx = HookContext(event_type="tool.post_call")
        results = await mgr.fire(
            "tool.post_call", ctx, tool_name="exec", result="fatal: crash"
        )
        assert len(results) == 1
        assert "[self-improvement]" in results[0]["result"]

    async def test_registered_hook_passes_clean_output(self) -> None:
        mgr = HookManager()
        register_self_improvement_hooks(mgr)
        ctx = HookContext(event_type="tool.post_call")
        results = await mgr.fire(
            "tool.post_call", ctx, tool_name="exec", result="all good"
        )
        assert len(results) == 1
        assert "[self-improvement]" not in results[0]["result"]


# ===========================================================================
# Part 5: Skill Loading — Integration Tests
# ===========================================================================


class TestSelfImprovementSkillLoading:
    """Verify the SKILL.md is discovered, marked always-on, and loaded into context."""

    @pytest.fixture
    def skills_loader(self, tmp_path: Path):
        from nanobot.agent.skills import SkillsLoader
        return SkillsLoader(workspace=tmp_path, builtin_skills_dir=Path("nanobot/skills"))

    def test_skill_is_listed(self, skills_loader) -> None:
        skills = skills_loader.list_skills(filter_unavailable=False)
        names = [s["name"] for s in skills]
        assert "self-improving-agent" in names

    def test_skill_metadata_has_correct_name(self, skills_loader) -> None:
        meta = skills_loader.get_skill_metadata("self-improving-agent")
        assert meta is not None
        assert meta["name"] == "self-improvement"

    def test_skill_is_always_on(self, skills_loader) -> None:
        always = skills_loader.get_always_skills()
        assert "self-improving-agent" in always

    def test_skill_content_loaded(self, skills_loader) -> None:
        content = skills_loader.load_skill("self-improving-agent")
        assert content is not None
        assert "Self-Improvement Skill" in content
        assert ".learnings/ERRORS.md" in content

    def test_skill_loaded_for_context_strips_frontmatter(self, skills_loader) -> None:
        content = skills_loader.load_skills_for_context(["self-improving-agent"])
        assert "---\nname:" not in content
        assert "Self-Improvement Skill" in content

    def test_skill_context_includes_key_sections(self, skills_loader) -> None:
        content = skills_loader.load_skills_for_context(["self-improving-agent"])
        assert "Quick Reference" in content
        assert "Logging Format" in content
        assert "Detection Triggers" in content
        assert "Simplify & Harden Feed" in content
        assert "Best Practices" in content

    def test_skill_has_learnings_templates(self) -> None:
        base = Path("nanobot/skills/self-improving-agent")
        assert (base / ".learnings" / "ERRORS.md").exists()
        assert (base / ".learnings" / "LEARNINGS.md").exists()
        assert (base / ".learnings" / "FEATURE_REQUESTS.md").exists()

    def test_skill_has_assets(self) -> None:
        base = Path("nanobot/skills/self-improving-agent")
        assert (base / "assets" / "LEARNINGS.md").exists()
        assert (base / "assets" / "SKILL-TEMPLATE.md").exists()

    def test_skill_has_extract_script(self) -> None:
        script = Path("nanobot/skills/self-improving-agent/scripts/extract-skill.sh")
        assert script.exists()


# ===========================================================================
# Part 6: Agent Loop Hook Pipeline — Integration Tests
# ===========================================================================


class TestAgentLoopHookPipeline:
    """Test that the agent loop correctly wires hooks and replaces results."""

    @pytest.fixture
    def hook_manager_with_si(self) -> HookManager:
        mgr = HookManager()
        register_self_improvement_hooks(mgr)
        return mgr

    async def test_hook_replaces_result_on_error(
        self, hook_manager_with_si: HookManager
    ) -> None:
        """Simulate the loop's result-replacement logic."""
        original_result = "Traceback (most recent call last):\n  ValueError: bad"

        ctx = HookContext(
            event_type="tool.post_call",
            session_key="cli:direct",
            sender_id="user",
            channel="cli",
        )
        hook_results = await hook_manager_with_si.fire(
            "tool.post_call", ctx,
            tool_name="exec",
            params={"command": "python bad.py"},
            result=original_result,
        )

        result = original_result
        for hr in hook_results:
            if isinstance(hr, dict) and "result" in hr:
                result = hr["result"]

        assert result != original_result
        assert result.startswith(original_result)
        assert "[self-improvement]" in result

    async def test_hook_does_not_replace_clean_result(
        self, hook_manager_with_si: HookManager
    ) -> None:
        original_result = "build successful"
        ctx = HookContext(event_type="tool.post_call")
        hook_results = await hook_manager_with_si.fire(
            "tool.post_call", ctx,
            tool_name="exec",
            params={"command": "make build"},
            result=original_result,
        )

        result = original_result
        for hr in hook_results:
            if isinstance(hr, dict) and "result" in hr:
                result = hr["result"]

        assert result == original_result

    async def test_hook_does_not_replace_for_non_exec(
        self, hook_manager_with_si: HookManager
    ) -> None:
        original_result = "error: file not found"
        ctx = HookContext(event_type="tool.post_call")
        hook_results = await hook_manager_with_si.fire(
            "tool.post_call", ctx,
            tool_name="read_file",
            params={"path": "/missing"},
            result=original_result,
        )

        result = original_result
        for hr in hook_results:
            if isinstance(hr, dict) and "result" in hr:
                result = hr["result"]

        assert result == original_result

    async def test_multiple_hooks_chain_correctly(self) -> None:
        """When multiple hooks are registered, all fire and last write wins."""
        mgr = HookManager()
        register_self_improvement_hooks(mgr)

        class AppendHook(Hook):
            name = "append_test"

            async def execute(self, context: HookContext, **kwargs: Any) -> Any:
                return {"tool_name": kwargs.get("tool_name"), "result": kwargs.get("result")}

        mgr.register("tool.post_call", AppendHook())

        ctx = HookContext(event_type="tool.post_call")
        hook_results = await mgr.fire(
            "tool.post_call", ctx, tool_name="exec", result="fatal: crash"
        )

        assert len(hook_results) == 2
        assert "[self-improvement]" in hook_results[0]["result"]

    async def test_has_hooks_guard(self, hook_manager_with_si: HookManager) -> None:
        assert hook_manager_with_si.has_hooks("tool.post_call")
        assert not hook_manager_with_si.has_hooks("nonexistent")


# ===========================================================================
# Part 7: AgentLoop._register_self_improvement_hooks — Integration
# ===========================================================================


class TestAgentLoopRegistration:
    """Test that AgentLoop properly registers the self-improvement hooks."""

    def _make_minimal_loop(self, tmp_path: Path):
        """Create a minimal AgentLoop with mocked dependencies."""
        from nanobot.agent.loop import AgentLoop

        loop = AgentLoop.__new__(AgentLoop)
        loop.hook_manager = HookManager()
        loop._register_self_improvement_hooks()
        return loop

    def test_hooks_registered_on_init(self, tmp_path: Path) -> None:
        loop = self._make_minimal_loop(tmp_path)
        assert loop.hook_manager.has_hooks("tool.post_call")

    async def test_hooks_fire_correctly_from_loop(self, tmp_path: Path) -> None:
        loop = self._make_minimal_loop(tmp_path)
        ctx = HookContext(event_type="tool.post_call")
        results = await loop.hook_manager.fire(
            "tool.post_call", ctx, tool_name="exec", result="TypeError: bad"
        )
        assert any("[self-improvement]" in r["result"] for r in results if isinstance(r, dict))


# ===========================================================================
# Part 8: SKILL.md Content Integrity
# ===========================================================================


class TestSkillMdContent:
    """Verify SKILL.md matches the reference spec sections."""

    @pytest.fixture
    def skill_content(self) -> str:
        return Path("nanobot/skills/self-improving-agent/SKILL.md").read_text(encoding="utf-8")

    def test_has_frontmatter(self, skill_content: str) -> None:
        assert skill_content.startswith("---\n")
        assert "\n---\n" in skill_content

    def test_frontmatter_name(self, skill_content: str) -> None:
        assert "name: self-improvement" in skill_content

    def test_frontmatter_always_true(self, skill_content: str) -> None:
        assert '"always": true' in skill_content

    def test_has_quick_reference_table(self, skill_content: str) -> None:
        assert "## Quick Reference" in skill_content
        assert "`.learnings/ERRORS.md`" in skill_content
        assert "`.learnings/LEARNINGS.md`" in skill_content
        assert "`.learnings/FEATURE_REQUESTS.md`" in skill_content

    def test_has_logging_format_sections(self, skill_content: str) -> None:
        assert "## Logging Format" in skill_content
        assert "### Learning Entry" in skill_content
        assert "### Error Entry" in skill_content
        assert "### Feature Request Entry" in skill_content

    def test_has_id_format(self, skill_content: str) -> None:
        assert "LRN-YYYYMMDD-XXX" in skill_content
        assert "ERR-YYYYMMDD-XXX" in skill_content
        assert "FEAT-YYYYMMDD-XXX" in skill_content

    def test_has_resolving_entries(self, skill_content: str) -> None:
        assert "## Resolving Entries" in skill_content
        assert "in_progress" in skill_content
        assert "wont_fix" in skill_content
        assert "promoted" in skill_content

    def test_has_promotion_section(self, skill_content: str) -> None:
        assert "## Promoting to Project Memory" in skill_content
        assert "AGENTS.md" in skill_content
        assert "USER.md" in skill_content
        assert "SOUL.md" in skill_content
        assert "TOOLS.md" in skill_content

    def test_has_recurring_pattern_detection(self, skill_content: str) -> None:
        assert "## Recurring Pattern Detection" in skill_content
        assert "See Also" in skill_content

    def test_has_simplify_and_harden_feed(self, skill_content: str) -> None:
        assert "## Simplify & Harden Feed" in skill_content
        assert "Pattern-Key" in skill_content
        assert "Recurrence-Count" in skill_content
        assert "Recurrence-Count >= 3" in skill_content

    def test_has_periodic_review(self, skill_content: str) -> None:
        assert "## Periodic Review" in skill_content
        assert "### Quick Status Check" in skill_content

    def test_has_detection_triggers(self, skill_content: str) -> None:
        assert "## Detection Triggers" in skill_content
        assert "**Corrections**" in skill_content
        assert "**Feature Requests**" in skill_content
        assert "**Knowledge Gaps**" in skill_content
        assert "**Errors**" in skill_content

    def test_has_priority_guidelines(self, skill_content: str) -> None:
        assert "## Priority Guidelines" in skill_content
        assert "critical" in skill_content
        assert "high" in skill_content
        assert "medium" in skill_content
        assert "low" in skill_content

    def test_has_area_tags(self, skill_content: str) -> None:
        assert "## Area Tags" in skill_content
        for area in ("frontend", "backend", "infra", "tests", "docs", "config"):
            assert area in skill_content

    def test_has_skill_extraction(self, skill_content: str) -> None:
        assert "## Automatic Skill Extraction" in skill_content
        assert "promoted_to_skill" in skill_content

    def test_has_gitignore_options(self, skill_content: str) -> None:
        assert "## Gitignore Options" in skill_content

    def test_has_best_practices(self, skill_content: str) -> None:
        assert "## Best Practices" in skill_content
        assert "Log immediately" in skill_content


# ===========================================================================
# Part 9: Supporting Files Integrity
# ===========================================================================


class TestSupportingFiles:
    """Verify all required supporting files exist and have correct content."""

    def test_errors_template(self) -> None:
        content = Path("nanobot/skills/self-improving-agent/.learnings/ERRORS.md").read_text()
        assert "Errors Log" in content

    def test_learnings_template(self) -> None:
        content = Path("nanobot/skills/self-improving-agent/.learnings/LEARNINGS.md").read_text()
        assert "Learnings Log" in content

    def test_feature_requests_template(self) -> None:
        content = Path("nanobot/skills/self-improving-agent/.learnings/FEATURE_REQUESTS.md").read_text()
        assert "Feature Requests" in content

    def test_assets_learnings_has_status_definitions(self) -> None:
        content = Path("nanobot/skills/self-improving-agent/assets/LEARNINGS.md").read_text()
        assert "Status Definitions" in content
        assert "promoted_to_skill" in content

    def test_assets_skill_template_has_frontmatter(self) -> None:
        content = Path("nanobot/skills/self-improving-agent/assets/SKILL-TEMPLATE.md").read_text()
        assert "name: skill-name-here" in content

    def test_extract_script_is_bash(self) -> None:
        content = Path("nanobot/skills/self-improving-agent/scripts/extract-skill.sh").read_text()
        assert content.startswith("#!/bin/bash")

    def test_extract_script_validates_skill_name(self) -> None:
        content = Path("nanobot/skills/self-improving-agent/scripts/extract-skill.sh").read_text()
        assert "^[a-z0-9]" in content

    def test_examples_file_has_all_entry_types(self) -> None:
        content = Path("nanobot/skills/self-improving-agent/references/examples.md").read_text()
        assert "[LRN-" in content
        assert "[ERR-" in content
        assert "[FEAT-" in content
        assert "promoted_to_skill" in content


# ===========================================================================
# Part 10: Hooks __init__ exports
# ===========================================================================


class TestHooksModuleExports:
    def test_hook_exported(self) -> None:
        from nanobot.hooks import Hook
        assert Hook is not None

    def test_hook_context_exported(self) -> None:
        from nanobot.hooks import HookContext
        assert HookContext is not None

    def test_hook_manager_exported(self) -> None:
        from nanobot.hooks import HookManager
        assert HookManager is not None

    def test_self_improvement_hook_exported(self) -> None:
        from nanobot.hooks import SelfImprovementHook
        assert SelfImprovementHook is not None


# ===========================================================================
# Part 11: Workspace Bootstrap — .learnings/ auto-creation
# ===========================================================================


class TestWorkspaceBootstrap:
    """Verify sync_workspace_templates creates .learnings/ with template files."""

    def test_sync_creates_learnings_dir(self, tmp_path: Path) -> None:
        from nanobot.utils.helpers import sync_workspace_templates

        sync_workspace_templates(tmp_path, silent=True)
        learnings = tmp_path / ".learnings"
        assert learnings.is_dir()

    def test_sync_creates_errors_md(self, tmp_path: Path) -> None:
        from nanobot.utils.helpers import sync_workspace_templates

        sync_workspace_templates(tmp_path, silent=True)
        errors = tmp_path / ".learnings" / "ERRORS.md"
        assert errors.exists()
        assert "Errors Log" in errors.read_text()

    def test_sync_creates_learnings_md(self, tmp_path: Path) -> None:
        from nanobot.utils.helpers import sync_workspace_templates

        sync_workspace_templates(tmp_path, silent=True)
        learnings = tmp_path / ".learnings" / "LEARNINGS.md"
        assert learnings.exists()
        assert "Learnings Log" in learnings.read_text()

    def test_sync_creates_feature_requests_md(self, tmp_path: Path) -> None:
        from nanobot.utils.helpers import sync_workspace_templates

        sync_workspace_templates(tmp_path, silent=True)
        feat = tmp_path / ".learnings" / "FEATURE_REQUESTS.md"
        assert feat.exists()
        assert "Feature Requests" in feat.read_text()

    def test_sync_does_not_overwrite_existing_learnings(self, tmp_path: Path) -> None:
        from nanobot.utils.helpers import sync_workspace_templates

        learnings_dir = tmp_path / ".learnings"
        learnings_dir.mkdir()
        errors = learnings_dir / "ERRORS.md"
        errors.write_text("# My custom errors\n\n## [ERR-20260310-001] test\n")

        sync_workspace_templates(tmp_path, silent=True)
        assert "My custom errors" in errors.read_text()

    def test_sync_returns_created_files(self, tmp_path: Path) -> None:
        from nanobot.utils.helpers import sync_workspace_templates

        added = sync_workspace_templates(tmp_path, silent=True)
        learnings_files = [f for f in added if ".learnings" in f]
        assert len(learnings_files) == 3
