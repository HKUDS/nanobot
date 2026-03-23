# Loop Extraction Test Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add dedicated unit tests for the three modules extracted from `AgentLoop` during LAN-213–216: `role_switching.py`, `verifier.py`, and `tool_setup.py`.

**Architecture:** Each module gets its own test file with lightweight fakes — no `AgentLoop` instantiation. Tests target the module's public interface in isolation. Follows existing conventions: `ScriptedProvider`, `pytest-asyncio` auto mode, `@pytest.mark.parametrize`.

**Tech Stack:** pytest, pytest-asyncio, unittest.mock (for observability no-ops only)

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `tests/test_role_switching.py` | Unit tests for `TurnRoleManager.apply`, `reset`, `_filter_tools` |
| Create | `tests/test_verifier.py` | Unit tests for `AnswerVerifier.verify`, `attempt_recovery`, `build_no_answer_explanation`, question detection, grounding confidence |
| Create | `tests/test_tool_setup.py` | Unit tests for `register_default_tools` — tool count, allow/deny filtering, conditional registration |

No production code changes.

---

### Task 1: `test_role_switching.py` — Fixtures and apply/reset tests

**Files:**
- Create: `tests/test_role_switching.py`
- Reference: `nanobot/agent/role_switching.py`

- [ ] **Step 1: Create test file with fixtures**

```python
"""Unit tests for TurnRoleManager (extracted from AgentLoop, LAN-214)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from nanobot.agent.role_switching import TurnRoleManager, TurnContext
from nanobot.config.schema import AgentRoleConfig


# -- Fakes satisfying _LoopLike Protocol ----------------------------------


@dataclass
class FakeContext:
    role_system_prompt: str = ""


@dataclass
class FakeDispatcher:
    role_name: str = ""


@dataclass
class FakeTools:
    """Dict-backed stub for ToolExecutor's snapshot/restore/unregister."""

    _tools: dict[str, str] = field(default_factory=dict)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def snapshot(self) -> dict[str, str]:
        return dict(self._tools)

    def restore(self, snap: dict[str, str]) -> None:
        self._tools = snap

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)


@dataclass
class FakeRoleConfig:
    name: str = "general"


@dataclass
class FakeLoop:
    model: str = "default-model"
    temperature: float = 0.7
    max_iterations: int = 10
    role_name: str = "general"
    role_config: Any = field(default_factory=FakeRoleConfig)
    context: Any = field(default_factory=FakeContext)
    tools: Any = field(default_factory=FakeTools)
    _dispatcher: Any = field(default_factory=FakeDispatcher)
    _capabilities: Any = None
    exec_config: Any = None


@pytest.fixture
def loop() -> FakeLoop:
    return FakeLoop(
        tools=FakeTools(_tools={"read_file": "r", "exec": "e", "web_search": "w"}),
    )


@pytest.fixture
def manager(loop: FakeLoop) -> TurnRoleManager:
    return TurnRoleManager(loop)
```

- [ ] **Step 2: Add test_apply_captures_snapshot**

```python
class TestApply:
    def test_captures_snapshot(
        self, manager: TurnRoleManager, loop: FakeLoop
    ) -> None:
        role = AgentRoleConfig(name="code", description="Coder", model="gpt-4")
        ctx = manager.apply(role)
        assert ctx.model == "default-model"
        assert ctx.temperature == 0.7
        assert ctx.max_iterations == 10
        assert ctx.role_prompt == ""
```

- [ ] **Step 3: Add test_apply_overrides_model_temperature_iterations**

```python
    def test_overrides_model(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        role = AgentRoleConfig(name="code", description="", model="gpt-4")
        manager.apply(role)
        assert loop.model == "gpt-4"

    def test_overrides_temperature(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        role = AgentRoleConfig(name="code", description="", temperature=0.2)
        manager.apply(role)
        assert loop.temperature == 0.2

    def test_overrides_max_iterations(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        role = AgentRoleConfig(name="code", description="", max_iterations=3)
        manager.apply(role)
        assert loop.max_iterations == 3
```

- [ ] **Step 4: Add test_apply_sets_role_prompt_and_syncs_dispatcher**

```python
    def test_sets_role_system_prompt(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        role = AgentRoleConfig(name="code", description="", system_prompt="You are a coder.")
        manager.apply(role)
        assert loop.context.role_system_prompt == "You are a coder."

    def test_syncs_dispatcher_role_name(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        role = AgentRoleConfig(name="research", description="")
        manager.apply(role)
        assert loop._dispatcher.role_name == "research"
        assert loop.role_name == "research"

    def test_no_model_override_preserves_default(
        self, manager: TurnRoleManager, loop: FakeLoop
    ) -> None:
        role = AgentRoleConfig(name="code", description="", model=None)
        manager.apply(role)
        assert loop.model == "default-model"
```

- [ ] **Step 5: Add reset tests**

```python
class TestReset:
    def test_restores_all_values(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        role = AgentRoleConfig(
            name="code",
            description="",
            model="gpt-4",
            temperature=0.1,
            max_iterations=2,
            system_prompt="override",
            allowed_tools=["exec"],
        )
        ctx = manager.apply(role)
        # Verify overrides took effect
        assert loop.model == "gpt-4"
        assert loop.temperature == 0.1

        manager.reset(ctx)
        assert loop.model == "default-model"
        assert loop.temperature == 0.7
        assert loop.max_iterations == 10
        assert loop.context.role_system_prompt == ""
        assert loop.role_name == "general"

    def test_reset_none_is_noop(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        original_model = loop.model
        manager.reset(None)
        assert loop.model == original_model

    def test_reset_skips_tool_restore_when_no_filtering(
        self, manager: TurnRoleManager, loop: FakeLoop
    ) -> None:
        role = AgentRoleConfig(name="code", description="")
        ctx = manager.apply(role)
        assert ctx.tools is None
        # restore should NOT be called — tools stay as-is
        original_tools = dict(loop.tools._tools)
        manager.reset(ctx)
        assert loop.tools._tools == original_tools
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_role_switching.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add tests/test_role_switching.py
git commit -m "test(role_switching): add dedicated unit tests for TurnRoleManager apply/reset"
```

---

### Task 2: `test_role_switching.py` — Tool filtering tests

**Files:**
- Modify: `tests/test_role_switching.py`

- [ ] **Step 1: Add tool filtering tests**

```python
class TestFilterTools:
    def test_allowed_whitelist(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        role = AgentRoleConfig(name="limited", description="", allowed_tools=["exec"])
        ctx = manager.apply(role)
        assert loop.tools.tool_names == ["exec"]
        assert ctx.tools is not None  # snapshot was taken

    def test_denied_blacklist(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        role = AgentRoleConfig(name="safe", description="", denied_tools=["exec"])
        manager.apply(role)
        assert "exec" not in loop.tools.tool_names
        assert "read_file" in loop.tools.tool_names
        assert "web_search" in loop.tools.tool_names

    def test_noop_when_unset(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        role = AgentRoleConfig(name="open", description="")
        ctx = manager.apply(role)
        assert ctx.tools is None
        assert set(loop.tools.tool_names) == {"read_file", "exec", "web_search"}

    def test_reset_restores_filtered_tools(
        self, manager: TurnRoleManager, loop: FakeLoop
    ) -> None:
        original_names = set(loop.tools.tool_names)
        role = AgentRoleConfig(name="limited", description="", allowed_tools=["exec"])
        ctx = manager.apply(role)
        assert loop.tools.tool_names == ["exec"]

        manager.reset(ctx)
        assert set(loop.tools.tool_names) == original_names
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_role_switching.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_role_switching.py
git commit -m "test(role_switching): add tool filtering tests for allowed/denied lists"
```

---

### Task 3: `test_verifier.py` — Pure helper method tests

**Files:**
- Create: `tests/test_verifier.py`
- Reference: `nanobot/agent/verifier.py`

- [ ] **Step 1: Create test file with imports and _looks_like_question tests**

```python
"""Unit tests for AnswerVerifier (extracted from AgentLoop, LAN-215)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.agent.verifier import AnswerVerifier
from nanobot.providers.base import LLMResponse
from tests.helpers import ScriptedProvider


class TestLooksLikeQuestion:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("What is X?", True),
            ("how do I do this", True),
            ("is it ready?", True),
            ("who wrote this", True),
            ("can you help", True),
            ("Hello", False),
            ("Save this note", False),
            ("", False),
            ("  ", False),
            ("Tell me about cats", False),
            ("Something with a ? mark", True),
        ],
    )
    def test_question_detection(self, text: str, expected: bool) -> None:
        assert AnswerVerifier._looks_like_question(text) is expected
```

- [ ] **Step 2: Add build_no_answer_explanation tests**

```python
class TestBuildNoAnswerExplanation:
    def test_no_tool_results(self) -> None:
        result = AnswerVerifier.build_no_answer_explanation("What?", [])
        assert "did not produce" in result

    def test_exit_code_error(self) -> None:
        msgs = [{"role": "tool", "name": "exec", "content": "exit code: 1"}]
        result = AnswerVerifier.build_no_answer_explanation("What?", msgs)
        assert "no matching data" in result

    def test_permission_denied(self) -> None:
        msgs = [{"role": "tool", "name": "exec", "content": "permission denied"}]
        result = AnswerVerifier.build_no_answer_explanation("What?", msgs)
        assert "permission error" in result

    def test_question_input_suggests_rephrase(self) -> None:
        result = AnswerVerifier.build_no_answer_explanation("What is X?", [])
        assert "rephrasing" in result.lower() or "rephras" in result.lower()

    def test_statement_input_suggests_sharing(self) -> None:
        result = AnswerVerifier.build_no_answer_explanation("My name is Carlos", [])
        assert "share the fact" in result.lower()

    def test_quota_error(self) -> None:
        msgs = [{"role": "tool", "name": "web", "content": "429 rate limited"}]
        result = AnswerVerifier.build_no_answer_explanation("Search for X?", msgs)
        assert "quota" in result.lower() or "rate limit" in result.lower()
```

- [ ] **Step 3: Add _estimate_grounding_confidence tests**

```python
class TestEstimateGroundingConfidence:
    def _make_verifier(self, memory: Any = None) -> AnswerVerifier:
        provider = ScriptedProvider([])
        return AnswerVerifier(
            provider=provider,
            model="test-model",
            temperature=0.7,
            max_tokens=4096,
            verification_mode="off",
            memory_uncertainty_threshold=0.5,
            memory_store=memory,
        )

    def test_no_memory_returns_zero(self) -> None:
        v = self._make_verifier(memory=None)
        assert v._estimate_grounding_confidence("anything") == 0.0

    def test_empty_results_returns_zero(self) -> None:
        memory = type("FakeMemory", (), {"retrieve": lambda self, q, top_k=1: []})()
        v = self._make_verifier(memory=memory)
        assert v._estimate_grounding_confidence("anything") == 0.0

    def test_score_clamped_to_unit_interval(self) -> None:
        memory = type(
            "FakeMemory", (), {"retrieve": lambda self, q, top_k=1: [{"score": 1.5}]}
        )()
        v = self._make_verifier(memory=memory)
        assert v._estimate_grounding_confidence("anything") == 1.0

    def test_memory_exception_returns_zero(self) -> None:
        def _explode(q, top_k=1):
            raise RuntimeError("boom")

        memory = type("FakeMemory", (), {"retrieve": _explode})()
        v = self._make_verifier(memory=memory)
        assert v._estimate_grounding_confidence("anything") == 0.0

    def test_normal_score_returned(self) -> None:
        memory = type(
            "FakeMemory", (), {"retrieve": lambda self, q, top_k=1: [{"score": 0.75}]}
        )()
        v = self._make_verifier(memory=memory)
        assert v._estimate_grounding_confidence("anything") == 0.75
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_verifier.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_verifier.py
git commit -m "test(verifier): add unit tests for question detection, grounding, and explanations"
```

---

### Task 4: `test_verifier.py` — Async verify() and attempt_recovery() tests

**Files:**
- Modify: `tests/test_verifier.py`

- [ ] **Step 1: Add verify() tests**

These tests need to mock `langfuse_span` and `score_current_trace` since they are
observability side-effects. Use `unittest.mock.patch` with `new=` for the async
context manager.

```python
def _make_verifier_with_provider(
    provider: ScriptedProvider,
    mode: str = "always",
    memory: Any = None,
) -> AnswerVerifier:
    return AnswerVerifier(
        provider=provider,
        model="test-model",
        temperature=0.7,
        max_tokens=4096,
        verification_mode=mode,
        memory_uncertainty_threshold=0.5,
        memory_store=memory,
    )


@patch("nanobot.agent.verifier.score_current_trace", new=lambda **kw: None)
@patch("nanobot.agent.verifier.langfuse_span", new=_noop_span_cm)
class TestVerify:
    async def test_off_passthrough(self) -> None:
        provider = ScriptedProvider([])
        v = _make_verifier_with_provider(provider, mode="off")
        result, msgs = await v.verify("What?", "candidate", [])
        assert result == "candidate"
        assert len(provider.call_log) == 0

    async def test_on_uncertainty_skips_non_question(self) -> None:
        provider = ScriptedProvider([])
        v = _make_verifier_with_provider(provider, mode="on_uncertainty")
        result, _ = await v.verify("hello", "candidate", [])
        assert result == "candidate"
        assert len(provider.call_log) == 0

    async def test_always_high_confidence_passes(self) -> None:
        provider = ScriptedProvider([
            LLMResponse(content='{"confidence": 5, "issues": []}'),
        ])
        v = _make_verifier_with_provider(provider)
        result, _ = await v.verify("What?", "candidate", [])
        assert result == "candidate"

    async def test_always_low_confidence_revises(self) -> None:
        provider = ScriptedProvider([
            LLMResponse(content='{"confidence": 1, "issues": ["unsupported claim"]}'),
            LLMResponse(content="revised answer"),
        ])
        v = _make_verifier_with_provider(provider)
        msgs = [{"role": "assistant", "content": "candidate"}]
        result, updated_msgs = await v.verify("What?", "candidate", msgs)
        assert result == "revised answer"
        # System message with issues was injected
        system_msgs = [m for m in updated_msgs if m.get("role") == "system"]
        assert any("unsupported claim" in m["content"] for m in system_msgs)

    async def test_unparseable_json_passthrough(self) -> None:
        provider = ScriptedProvider([
            LLMResponse(content="not valid json"),
        ])
        v = _make_verifier_with_provider(provider)
        result, _ = await v.verify("What?", "candidate", [])
        assert result == "candidate"

    async def test_llm_exception_passthrough(self) -> None:
        provider = ScriptedProvider([])  # exhausted → will still return string
        # Override chat to raise
        async def _raise(**kwargs: Any) -> None:
            raise RuntimeError("LLM down")

        provider.chat = _raise  # type: ignore[assignment]
        v = _make_verifier_with_provider(provider)
        result, _ = await v.verify("What?", "candidate", [])
        assert result == "candidate"
```

The `_noop_span_cm` helper for mocking the async context manager:

```python
import contextlib


@contextlib.asynccontextmanager
async def _noop_span_cm(**kwargs: Any):
    yield None
```

Place this helper near the top of the file, after imports.

- [ ] **Step 2: Add attempt_recovery() tests**

```python
@patch("nanobot.agent.verifier.langfuse_span", new=_noop_span_cm)
class TestAttemptRecovery:
    async def test_recovery_success(self) -> None:
        provider = ScriptedProvider([
            LLMResponse(content="recovered answer"),
        ])
        v = _make_verifier_with_provider(provider)
        all_msgs = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "What is X?"},
        ]
        result = await v.attempt_recovery(
            channel="cli", chat_id="test", all_msgs=all_msgs
        )
        assert result == "recovered answer"

    async def test_recovery_missing_messages(self) -> None:
        provider = ScriptedProvider([])
        v = _make_verifier_with_provider(provider)
        # Only tool messages — no system or user
        all_msgs = [{"role": "tool", "name": "exec", "content": "output"}]
        result = await v.attempt_recovery(
            channel="cli", chat_id="test", all_msgs=all_msgs
        )
        assert result is None

    async def test_recovery_llm_exception(self) -> None:
        provider = ScriptedProvider([])

        async def _raise(**kwargs: Any) -> None:
            raise RuntimeError("boom")

        provider.chat = _raise  # type: ignore[assignment]
        v = _make_verifier_with_provider(provider)
        all_msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
        result = await v.attempt_recovery(
            channel="cli", chat_id="test", all_msgs=all_msgs
        )
        assert result is None

    async def test_recovery_error_finish_reason(self) -> None:
        provider = ScriptedProvider([
            LLMResponse(content="error detail", finish_reason="error"),
        ])
        v = _make_verifier_with_provider(provider)
        all_msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
        result = await v.attempt_recovery(
            channel="cli", chat_id="test", all_msgs=all_msgs
        )
        assert result is None
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_verifier.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_verifier.py
git commit -m "test(verifier): add async tests for verify() and attempt_recovery()"
```

---

### Task 5: `test_tool_setup.py` — Tool registration tests

**Files:**
- Create: `tests/test_tool_setup.py`
- Reference: `nanobot/agent/tool_setup.py`

- [ ] **Step 1: Create test file with fixtures**

```python
"""Unit tests for register_default_tools (extracted from AgentLoop, LAN-213)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from nanobot.agent.tool_executor import ToolExecutor
from nanobot.agent.tool_setup import register_default_tools
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.result_cache import ToolResultCache
from nanobot.config.schema import AgentRoleConfig, ExecToolConfig


class FakeSkillsLoader:
    """Stub that returns no skill tools by default."""

    def __init__(self, tools: list[Any] | None = None) -> None:
        self._tools = tools or []

    def discover_tools(self, skill_names: list[str] | None = None) -> list[Any]:
        return self._tools


async def _noop_publish(**kwargs: Any) -> None:
    pass


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    (tmp_path / "memory").mkdir()
    (tmp_path / "sessions" / "_placeholder").mkdir(parents=True)
    return tmp_path


def _register(
    workspace: Path,
    *,
    role_config: AgentRoleConfig | None = None,
    delegation_enabled: bool = True,
    cron_service: Any = None,
    skills_loader: Any = None,
) -> ToolExecutor:
    registry = ToolRegistry()
    tools = ToolExecutor(registry)
    register_default_tools(
        tools=tools,
        role_config=role_config,
        workspace=workspace,
        restrict_to_workspace=False,
        shell_mode="denylist",
        vision_model=None,
        exec_config=ExecToolConfig(timeout=30),
        brave_api_key=None,
        publish_outbound=_noop_publish,
        cron_service=cron_service,
        delegation_enabled=delegation_enabled,
        missions=Mock(),
        result_cache=Mock(spec=ToolResultCache),
        skills_enabled=bool(skills_loader),
        skills_loader=skills_loader or FakeSkillsLoader(),
    )
    return tools
```

- [ ] **Step 2: Add default registration and count tests**

```python
class TestRegisterDefaultTools:
    def test_default_tools_registered(self, tmp_workspace: Path) -> None:
        tools = _register(tmp_workspace)
        names = tools._registry.tool_names
        # Spot-check core tools are present
        for expected in ("read_file", "write_file", "edit_file", "list_dir",
                         "exec", "web_search", "web_fetch", "message",
                         "feedback", "check_email"):
            assert expected in names, f"Missing expected tool: {expected}"

    def test_delegation_tools_present_when_enabled(self, tmp_workspace: Path) -> None:
        tools = _register(tmp_workspace, delegation_enabled=True)
        names = tools._registry.tool_names
        for expected in ("delegate", "delegate_parallel",
                         "mission_start", "mission_status",
                         "mission_list", "mission_cancel"):
            assert expected in names, f"Missing delegation tool: {expected}"

    def test_expected_tool_count(self, tmp_workspace: Path) -> None:
        """Regression guard: total tool count from auditing tool_setup.py."""
        tools = _register(tmp_workspace)
        # Count derived from manual audit of tool_setup.py at commit 7470a43:
        # filesystem(4) + spreadsheet(1) + pptx_read(1) + pptx_analyze(1) +
        # exec(1) + web_search(1) + web_fetch(1) + message(1) + feedback(1) +
        # email(1) + delegation(6) + scratchpad(2) + cache_get_slice(1) +
        # excel_get_rows(1) + excel_find(1) + pptx_get_slide(1) +
        # query_data(1) + describe_data(1) = 27
        # (no cron — cron_service=None)
        assert len(tools._registry) == 27
```

- [ ] **Step 3: Add allow/deny filtering tests**

```python
    def test_allowed_tools_whitelist(self, tmp_workspace: Path) -> None:
        role = AgentRoleConfig(
            name="restricted", description="", allowed_tools=["exec", "read_file"]
        )
        tools = _register(tmp_workspace, role_config=role)
        names = set(tools._registry.tool_names)
        assert names == {"exec", "read_file"}

    def test_denied_tools_blacklist(self, tmp_workspace: Path) -> None:
        role = AgentRoleConfig(name="safe", description="", denied_tools=["exec"])
        tools = _register(tmp_workspace, role_config=role)
        names = tools._registry.tool_names
        assert "exec" not in names
        assert "read_file" in names
```

- [ ] **Step 4: Add conditional registration tests**

```python
    def test_delegation_disabled_skips_tools(self, tmp_workspace: Path) -> None:
        tools = _register(tmp_workspace, delegation_enabled=False)
        names = tools._registry.tool_names
        for absent in ("delegate", "delegate_parallel",
                       "mission_start", "mission_status",
                       "mission_list", "mission_cancel"):
            assert absent not in names, f"Should not register: {absent}"

    def test_no_cron_service_skips_cron(self, tmp_workspace: Path) -> None:
        tools = _register(tmp_workspace, cron_service=None)
        assert "cron" not in tools._registry.tool_names

    def test_cron_registered_when_service_provided(self, tmp_workspace: Path) -> None:
        tools = _register(tmp_workspace, cron_service=Mock())
        assert "cron" in tools._registry.tool_names

    def test_skills_tools_discovered(self, tmp_workspace: Path) -> None:
        from nanobot.agent.tools.base import Tool, ToolResult

        class FakeSkillTool(Tool):
            name = "fake_skill_tool"
            description = "A skill-provided tool"
            parameters: dict[str, Any] = {"type": "object", "properties": {}}

            async def execute(self, **kwargs: Any) -> ToolResult:
                return ToolResult.ok("ok")

        loader = FakeSkillsLoader(tools=[FakeSkillTool()])
        tools = _register(tmp_workspace, skills_loader=loader)
        assert "fake_skill_tool" in tools._registry.tool_names
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_tool_setup.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_tool_setup.py
git commit -m "test(tool_setup): add unit tests for register_default_tools"
```

---

### Task 6: Final validation

- [ ] **Step 1: Run all new tests together**

Run: `pytest tests/test_role_switching.py tests/test_verifier.py tests/test_tool_setup.py -v`
Expected: All ~32 tests PASS

- [ ] **Step 2: Run full test suite to check for regressions**

Run: `make check`
Expected: lint + typecheck + tests all pass

- [ ] **Step 3: Commit spec and plan docs**

```bash
git add docs/superpowers/specs/2026-03-21-loop-extraction-test-coverage-design.md
git add docs/superpowers/plans/2026-03-21-loop-extraction-test-coverage.md
git commit -m "docs: add spec and plan for loop extraction test coverage"
```
